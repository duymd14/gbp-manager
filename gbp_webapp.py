#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from gbp_manager import GBPManager, logger


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_LOCATIONS_FILE = BASE_DIR / "locations.json"
DEMO_LOCATIONS_FILE = BASE_DIR / "locations.example.json"


class GBPWebApp:
    def __init__(self):
        self.manager = GBPManager()
        if DEFAULT_LOCATIONS_FILE.exists():
            self.manager.load_locations_from_file(str(DEFAULT_LOCATIONS_FILE))
            logger.info(f"Đã nạp locations từ {DEFAULT_LOCATIONS_FILE}")
        elif DEMO_LOCATIONS_FILE.exists():
            # Dùng demo data nếu chưa có file thật — chạy ở chế độ mock
            self.manager.load_locations_from_file(str(DEMO_LOCATIONS_FILE))
            logger.warning("locations.json không tồn tại → dùng locations.example.json (chế độ demo)")

    def get_status(self):
        token_file = BASE_DIR / self.manager.config["TOKEN_FILE"]
        active_locations = [loc for loc in self.manager.locations if loc.get("active", True)]
        return {
            "authenticated": bool(self.manager.client.credentials and self.manager.client.credentials.valid),
            "token_file_exists": token_file.exists(),
            "token_file": str(token_file),
            "active_locations": len(active_locations),
            "total_locations": len(self.manager.locations),
            "last_checked_at": datetime.now().isoformat(),
        }

    def get_locations(self):
        locations = []
        for location in self.manager.locations:
            reviews = self.manager.client.get_reviews(location)
            ratings = []
            pending_count = 0
            for review in reviews:
                star = self.manager.template_mgr.get_star_rating_int(review.get("starRating", "THREE"))
                ratings.append(star)
                reply = (review.get("reviewReply") or {}).get("comment", "").strip()
                if not reply:
                    pending_count += 1

            avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else None
            locations.append(
                {
                    "id": location.get("id"),
                    "name": location.get("name", ""),
                    "area": location.get("area", ""),
                    "city": location.get("city", ""),
                    "type": location.get("type", "restaurant"),
                    "website": location.get("website", ""),
                    "rating": avg_rating,
                    "reviews": len(reviews),
                    "views": "-",
                    "active": location.get("active", True),
                    "pending_reviews": pending_count,
                }
            )
        return locations

    def get_templates(self):
        return self.manager.template_mgr.templates

    def get_reviews(self, location_id=None, pending_only=False):
        data = []
        counter = 1
        for location in self.manager.locations:
            if location_id and str(location.get("id")) != str(location_id):
                continue

            for review in self.manager.client.get_reviews(location):
                reply_text = (review.get("reviewReply") or {}).get("comment", "").strip()
                if pending_only and reply_text:
                    continue

                comment = review.get("comment", "") or ""
                created_at = review.get("createTime", "")
                data.append(
                    {
                        "id": counter,
                        "review_name": review.get("name", ""),
                        "location_id": location.get("id"),
                        "location_name": location.get("name", ""),
                        "location_label": f"{location.get('name', '')} - {location.get('city', '')}",
                        "city": location.get("city", ""),
                        "type": location.get("type", "restaurant"),
                        "name": review.get("reviewer", {}).get("displayName", "Khách ẩn danh"),
                        "stars": self.manager.template_mgr.get_star_rating_int(review.get("starRating", "THREE")),
                        "date": self._format_date(created_at),
                        "lang": self.manager.template_mgr.detect_language(comment) if comment else self.manager.config["DEFAULT_REPLY_LANG"],
                        "text": comment,
                        "replied": bool(reply_text),
                        "reply": reply_text,
                        "create_time": created_at,
                    }
                )
                counter += 1

        data.sort(key=lambda item: item.get("create_time", ""), reverse=True)
        return data

    def suggest_reply(self, payload):
        location = self.manager.get_location_by_id(payload.get("location_id"))
        if not location:
            raise ValueError("Không tìm thấy location")

        review = {
            "starRating": self._star_label(payload.get("stars", 3)),
            "reviewer": {"displayName": payload.get("name", "Khách ẩn danh")},
            "comment": payload.get("text", ""),
        }
        reply = self.manager.template_mgr.get_reply(review, location, payload.get("lang"))
        if not reply:
            raise ValueError("Không tạo được reply gợi ý")
        return {"reply": reply}

    def submit_reply(self, payload):
        location = self.manager.get_location_by_id(payload.get("location_id"))
        if not location:
            raise ValueError("Không tìm thấy location")

        review_name = payload.get("review_name")
        reply_text = (payload.get("reply_text") or "").strip()
        if not review_name or not reply_text:
            raise ValueError("Thiếu review_name hoặc reply_text")

        ok = self.manager.client.reply_to_review(location, review_name, reply_text)
        if not ok:
            raise RuntimeError("Gửi reply thất bại")

        return {"success": True}

    def auto_reply_all(self):
        results = {"replied": 0, "skipped": 0, "suggested_negative": 0}
        for review in self.get_reviews(pending_only=True):
            stars = review["stars"]
            if stars <= 2 and self.manager.config.get("ALERT_1_2_STAR"):
                results["suggested_negative"] += 1
                results["skipped"] += 1
                continue
            if stars == 5 and not self.manager.config.get("AUTO_REPLY_5_STAR"):
                results["skipped"] += 1
                continue
            if stars == 4 and not self.manager.config.get("AUTO_REPLY_4_STAR"):
                results["skipped"] += 1
                continue

            suggestion = self.suggest_reply(review)["reply"]
            self.submit_reply(
                {
                    "location_id": review["location_id"],
                    "review_name": review["review_name"],
                    "reply_text": suggestion,
                }
            )
            results["replied"] += 1

        return results

    def publish_post(self, payload):
        location = self.manager.get_location_by_id(payload.get("location_id"))
        if not location:
            raise ValueError("Không tìm thấy location")

        content = (payload.get("content") or "").strip()
        cta_button = (payload.get("cta_button") or self.manager.config["DEFAULT_CTA_BUTTON"]).strip().upper()
        cta_url = (payload.get("cta_url") or location.get("website", "")).strip()

        if not content:
            raise ValueError("Nội dung bài đăng đang trống")

        post_data = {
            "summary": content,
            "topicType": "STANDARD",
            "callToAction": {
                "actionType": cta_button,
                "url": cta_url,
            },
        }

        ok = self.manager.client.create_post(location, post_data)
        if not ok:
            raise RuntimeError("Đăng bài thất bại")

        return {"success": True}

    def authenticate(self):
        self.manager.authenticate()
        self.manager.client._authenticate()
        return self.get_status()

    @staticmethod
    def _star_label(stars):
        mapping = {1: "ONE", 2: "TWO", 3: "THREE", 4: "FOUR", 5: "FIVE"}
        return mapping.get(int(stars), "THREE")

    @staticmethod
    def _format_date(value):
        if not value:
            return ""
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.strftime("%d.%m.%Y")
        except ValueError:
            return value


APP = GBPWebApp()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            return self._write_json(APP.get_status())
        if parsed.path == "/api/locations":
            return self._write_json({"locations": APP.get_locations()})
        if parsed.path == "/api/reviews":
            query = parse_qs(parsed.query)
            location_id = query.get("location_id", [None])[0]
            pending_only = query.get("pending_only", ["0"])[0] == "1"
            return self._write_json({"reviews": APP.get_reviews(location_id=location_id, pending_only=pending_only)})
        if parsed.path == "/api/templates":
            return self._write_json({"templates": APP.get_templates()})
        if parsed.path == "/":
            self.path = "/gbp_dashboard.html"
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        payload = self._read_json_body()
        try:
            if parsed.path == "/api/auth":
                return self._write_json(APP.authenticate())
            if parsed.path == "/api/reply/suggest":
                return self._write_json(APP.suggest_reply(payload))
            if parsed.path == "/api/reply":
                return self._write_json(APP.submit_reply(payload))
            if parsed.path == "/api/reply-all":
                return self._write_json(APP.auto_reply_all())
            if parsed.path == "/api/posts/publish":
                return self._write_json(APP.publish_post(payload))
        except ValueError as exc:
            return self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            logger.exception("API error")
            return self._write_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def _read_json_body(self):
        raw_length = self.headers.get("Content-Length", "0")
        length = int(raw_length) if raw_length.isdigit() else 0
        if not length:
            return {}
        body = self.rfile.read(length).decode("utf-8")
        return json.loads(body)

    def _add_cors_headers(self):
        """Thêm CORS headers để cho phép frontend gọi API từ các origin khác"""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        """Xử lý preflight CORS request"""
        self.send_response(HTTPStatus.NO_CONTENT)
        self._add_cors_headers()
        self.end_headers()

    def _write_json(self, payload, status=HTTPStatus.OK):
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(encoded)


def main():
    # Railway dùng biến PORT, local dùng GBP_WEBAPP_PORT hoặc 8000
    port = int(os.environ.get("PORT", os.environ.get("GBP_WEBAPP_PORT", "8000")))
    # Bind 0.0.0.0 để Railway có thể expose ra ngoài internet
    host = "0.0.0.0"
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"GBP webapp running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
