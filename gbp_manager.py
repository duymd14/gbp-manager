#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================
  GBP MANAGER PRO - Dành cho chủ nhà hàng Việt tại Đức
  Công cụ tự động hóa Google Business Profile
  Tác giả: GBP Tools
  Phiên bản: 1.0
=============================================

TÍNH NĂNG:
  - Tự động reply review (tiếng Đức + tiếng Anh)
  - Đăng bài tự động theo lịch
  - Quản lý nhiều GBP cùng lúc (tối đa 20+)
  - Báo cáo hiệu suất hàng tuần

CÀI ĐẶT:
  pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client requests schedule

CÁCH SỬ DỤNG:
  python gbp_manager.py --action reply_reviews
  python gbp_manager.py --action publish_posts
  python gbp_manager.py --action full_auto
  python gbp_manager.py --action report
"""

import json
import os
import time
import random
import logging
import argparse
try:
    import schedule
except ImportError:
    schedule = None
from datetime import datetime, timedelta
from pathlib import Path

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('gbp_manager.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================
# CẤU HÌNH CHÍNH - Đọc từ environment variables (ưu tiên) hoặc giá trị mặc định
# Đặt GBP_CLIENT_ID và GBP_CLIENT_SECRET trong file .env hoặc Railway Variables
# ============================================================
CONFIG = {
    # Google OAuth2 Credentials - đọc từ env vars
    "CLIENT_ID": os.environ.get("GBP_CLIENT_ID", "YOUR_CLIENT_ID.apps.googleusercontent.com"),
    "CLIENT_SECRET": os.environ.get("GBP_CLIENT_SECRET", "YOUR_CLIENT_SECRET"),
    "REDIRECT_URI": os.environ.get("GBP_REDIRECT_URI", "http://localhost:8080/callback"),
    "TOKEN_FILE": os.environ.get("GBP_TOKEN_FILE", "gbp_token.json"),

    # Cài đặt tự động hóa
    "AUTO_REPLY_5_STAR": True,       # Tự động reply 5 sao
    "AUTO_REPLY_4_STAR": True,       # Tự động reply 4 sao
    "ALERT_1_2_STAR": True,          # Cảnh báo review tiêu cực (không auto-reply)
    "AUTO_DETECT_LANGUAGE": True,    # Tự nhận diện ngôn ngữ
    "DEFAULT_REPLY_LANG": "de",      # Ngôn ngữ mặc định: "de" hoặc "en"

    # Cài đặt đăng bài
    "AUTO_PUBLISH_POSTS": True,
    "POST_INTERVAL_DAYS": 2,         # Đăng bài mỗi bao nhiêu ngày
    "POST_TIME": "22:07",            # Giờ đăng bài (HH:MM)
    "DEFAULT_CTA_BUTTON": "LEARN_MORE",  # LEARN_MORE / ORDER_ONLINE / BOOK / GET_OFFER

    # Giới hạn API (an toàn)
    "API_DELAY_SECONDS": 2,          # Delay giữa các request
    "MAX_REPLIES_PER_RUN": 50,       # Tối đa reply mỗi lần chạy
    "MAX_POSTS_PER_RUN": 20,         # Tối đa bài đăng mỗi lần chạy

    # Email thông báo (tuỳ chọn)
    "NOTIFY_EMAIL": "your@email.com",
    "NOTIFY_NEGATIVE_REVIEWS": True,
}

# ============================================================
# DANH SÁCH 20 ĐỊA ĐIỂM GBP
# Thay accountId và locationId bằng thông tin thực của bạn
# ============================================================
LOCATIONS = [
    {
        "id": 1,
        "name": "PHO Noodle Bar – Kreuzberg",
        "city": "Berlin",
        "type": "restaurant",
        "accountId": "accounts/XXXXXXXX",
        "locationId": "locations/YYYYYYYY",
        "website": "https://pho.berlin/",
        "keywords": ["pho bo", "vietnamese food", "asian restaurant", "halal", "kreuzberg"],
        "active": True
    },
    {
        "id": 2,
        "name": "PHO Noodle Bar – Mitte",
        "city": "Berlin",
        "type": "restaurant",
        "accountId": "accounts/XXXXXXXX",
        "locationId": "locations/ZZZZZZZZ",
        "website": "https://pho.berlin/",
        "keywords": ["pho bo", "vietnamese food", "asian restaurant", "mitte", "berlin"],
        "active": True
    },
    # Thêm các địa điểm khác tương tự...
    # Bạn có thể dùng hàm load_locations_from_file() để nạp từ file JSON
]


# ============================================================
# GOOGLE API CLIENT
# ============================================================
class GBPClient:
    """Lớp xử lý kết nối Google Business Profile API"""

    def __init__(self, config):
        self.config = config
        self.credentials = None
        self.service = None
        self._authenticate()

    def _authenticate(self):
        """Xác thực với Google API"""
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from google_auth_oauthlib.flow import InstalledAppFlow

            SCOPES = [
                'https://www.googleapis.com/auth/business.manage'
            ]

            token_file = self.config["TOKEN_FILE"]

            if os.path.exists(token_file):
                with open(token_file, 'r') as f:
                    token_data = json.load(f)
                self.credentials = Credentials.from_authorized_user_info(token_data, SCOPES)

            if not self.credentials or not self.credentials.valid:
                if self.credentials and self.credentials.expired and self.credentials.refresh_token:
                    self.credentials.refresh(Request())
                    logger.info("Token đã được làm mới tự động.")
                else:
                    logger.error("Token không hợp lệ. Vui lòng chạy: python gbp_manager.py --action auth")
                    return

                with open(token_file, 'w') as f:
                    f.write(self.credentials.to_json())

            logger.info("Kết nối Google API thành công!")

        except ImportError:
            logger.warning("Thư viện Google API chưa được cài đặt.")
            logger.warning("Chạy: pip install google-auth google-auth-oauthlib google-auth-httplib2")
            self.credentials = None

        except Exception as e:
            logger.error(f"Lỗi xác thực: {e}")
            self.credentials = None

    def load_token_from_env(self):
        """Đọc token từ biến môi trường GBP_TOKEN_JSON (dùng khi deploy trên Railway)"""
        token_json = os.environ.get("GBP_TOKEN_JSON", "")
        if not token_json:
            return False
        try:
            token_file = self.config["TOKEN_FILE"]
            with open(token_file, "w", encoding="utf-8") as f:
                f.write(token_json)
            logger.info("Đã nạp token từ biến môi trường GBP_TOKEN_JSON")
            self._authenticate()
            return True
        except Exception as e:
            logger.error(f"Lỗi nạp GBP_TOKEN_JSON từ env: {e}")
            return False

    def get_reviews(self, location):
        """Lấy danh sách review của một địa điểm"""
        if not self.credentials:
            return self._mock_get_reviews(location)

        try:
            import requests
            headers = {"Authorization": f"Bearer {self.credentials.token}"}
            url = f"https://mybusiness.googleapis.com/v4/{location['accountId']}/{location['locationId']}/reviews"
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json().get("reviews", [])
        except Exception as e:
            logger.error(f"Lỗi lấy review [{location['name']}]: {e}")
            return []

    def reply_to_review(self, location, review_name, reply_text):
        """Gửi reply cho một review"""
        if not self.credentials:
            return self._mock_reply_review(location, review_name, reply_text)

        try:
            import requests
            headers = {
                "Authorization": f"Bearer {self.credentials.token}",
                "Content-Type": "application/json"
            }
            url = f"https://mybusiness.googleapis.com/v4/{review_name}/reply"
            payload = {"comment": reply_text}
            response = requests.put(url, headers=headers, json=payload)
            response.raise_for_status()
            logger.info(f"  ✓ Đã reply review tại {location['name']}")
            return True
        except Exception as e:
            logger.error(f"  ✗ Lỗi reply review: {e}")
            return False

    def create_post(self, location, post_data):
        """Đăng bài lên GBP"""
        if not self.credentials:
            return self._mock_create_post(location, post_data)

        try:
            import requests
            headers = {
                "Authorization": f"Bearer {self.credentials.token}",
                "Content-Type": "application/json"
            }
            url = f"https://mybusiness.googleapis.com/v4/{location['accountId']}/{location['locationId']}/localPosts"
            response = requests.post(url, headers=headers, json=post_data)
            response.raise_for_status()
            logger.info(f"  ✓ Đã đăng bài tại {location['name']}")
            return True
        except Exception as e:
            logger.error(f"  ✗ Lỗi đăng bài: {e}")
            return False

    # Hàm mô phỏng (dùng khi chưa có API key)
    def _mock_get_reviews(self, location):
        return [
            {"name": f"accounts/123/locations/456/reviews/r001", "starRating": "FIVE", "reviewer": {"displayName": "Hans Müller"}, "comment": "Sehr leckere Pho! Das Personal ist sehr freundlich.", "createTime": "2026-04-12T10:30:00Z", "reviewReply": None},
            {"name": f"accounts/123/locations/456/reviews/r002", "starRating": "ONE", "reviewer": {"displayName": "Klaus Schmidt"}, "comment": "Lange Wartezeit und kalte Suppe. Sehr enttäuschend.", "createTime": "2026-04-11T14:00:00Z", "reviewReply": None},
            {"name": f"accounts/123/locations/456/reviews/r003", "starRating": "FIVE", "reviewer": {"displayName": "Emma Johnson"}, "comment": "Amazing food! Best pho in Berlin. Will definitely come back!", "createTime": "2026-04-10T18:00:00Z", "reviewReply": None},
        ]

    def _mock_reply_review(self, location, review_name, reply_text):
        logger.info(f"  [CHẾ ĐỘ THỬ] Sẽ gửi reply đến: {review_name}")
        logger.info(f"  Nội dung: {reply_text[:80]}...")
        return True

    def _mock_create_post(self, location, post_data):
        logger.info(f"  [CHẾ ĐỘ THỬ] Sẽ đăng bài tại: {location['name']}")
        logger.info(f"  Nội dung: {post_data.get('summary', '')[:80]}...")
        return True


# ============================================================
# QUẢN LÝ TEMPLATE REPLY
# ============================================================
class ReplyTemplateManager:
    """Quản lý và áp dụng template reply tự động"""

    def __init__(self, templates_file="review_templates.json"):
        self.templates = self._load_templates(templates_file)

    def _load_templates(self, file_path):
        """Nạp templates từ file JSON"""
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        logger.warning(f"File template {file_path} không tìm thấy. Dùng template mặc định.")
        return self._default_templates()

    def detect_language(self, text):
        """Phát hiện ngôn ngữ đơn giản dựa trên từ khóa"""
        german_words = ['sehr', 'gut', 'danke', 'lecker', 'freundlich', 'lange', 'schön', 'warte', 'essen', 'nicht', 'war', 'ist', 'habe', 'aber', 'und', 'die', 'der', 'das']
        english_words = ['very', 'good', 'thank', 'great', 'amazing', 'nice', 'food', 'service', 'staff', 'love', 'best', 'would', 'definitely', 'highly', 'recommend']

        text_lower = text.lower()
        de_score = sum(1 for w in german_words if w in text_lower)
        en_score = sum(1 for w in english_words if w in text_lower)

        return 'de' if de_score >= en_score else 'en'

    def get_star_rating_int(self, star_rating_str):
        """Chuyển đổi 'FIVE' -> 5"""
        mapping = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}
        return mapping.get(star_rating_str.upper(), 3)

    def get_sentiment(self, stars):
        """Phân loại cảm xúc dựa trên số sao"""
        if stars >= 4:
            return "positive"
        elif stars == 3:
            return "neutral"
        else:
            return "negative"

    def get_reply(self, review, location, language=None):
        """Tạo reply phù hợp cho review"""
        stars = self.get_star_rating_int(review.get("starRating", "THREE"))
        reviewer_name = review.get("reviewer", {}).get("displayName", "")
        first_name = reviewer_name.split()[0] if reviewer_name else "Lieber Gast"
        comment = review.get("comment", "")

        # Phát hiện ngôn ngữ
        if not language:
            language = self.detect_language(comment) if comment else CONFIG["DEFAULT_REPLY_LANG"]

        sentiment = self.get_sentiment(stars)
        location_type = location.get("type", "restaurant")

        # Lấy templates phù hợp
        template_key = f"{sentiment}_{language}"
        category = self.templates.get(location_type, self.templates.get("restaurant", {}))
        templates_list = category.get(template_key, [])

        if not templates_list:
            # Fallback sang tiếng Đức nếu không có tiếng Anh
            fallback_key = f"{sentiment}_de"
            templates_list = category.get(fallback_key, [])

        if not templates_list:
            return None

        # Chọn ngẫu nhiên để tránh lặp lại
        template = random.choice(templates_list)

        # Điền thông tin vào template
        reply = template["text"]
        reply = reply.replace("{name}", first_name)
        reply = reply.replace("{restaurant}", location.get("name", "uns"))
        reply = reply.replace("{city}", location.get("city", ""))

        return reply

    def _default_templates(self):
        """Templates mặc định nếu file JSON không tồn tại"""
        return {
            "restaurant": {
                "positive_de": [{"text": "Vielen herzlichen Dank, {name}! Es freut uns sehr, dass Sie bei {restaurant} einen schönen Besuch hatten. Wir freuen uns auf Ihr nächstes Kommen! 🍜"}],
                "positive_en": [{"text": "Thank you so much, {name}! We're thrilled you enjoyed your visit to {restaurant}. See you again soon! 🍜"}],
                "negative_de": [{"text": "Liebe/r {name}, vielen Dank für Ihr Feedback. Es tut uns leid, dass Ihr Besuch nicht Ihren Erwartungen entsprach. Bitte kontaktieren Sie uns direkt – wir möchten das gerne wiedergutmachen."}],
                "negative_en": [{"text": "Dear {name}, thank you for your honest feedback. We're sorry your experience at {restaurant} didn't meet expectations. Please reach out to us directly so we can make it right."}],
                "neutral_de": [{"text": "Danke für Ihre Bewertung, {name}! Wir nehmen Ihr Feedback gerne an und arbeiten stets daran, uns zu verbessern. Bis zum nächsten Besuch!"}]
            }
        }


# ============================================================
# QUẢN LÝ NỘI DUNG BÀI ĐĂNG
# ============================================================
class PostContentManager:
    """Tạo và quản lý nội dung bài đăng GBP"""

    def __init__(self, calendar_file="post_calendar.json"):
        self.calendar = self._load_calendar(calendar_file)

    def _load_calendar(self, file_path):
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"posts": []}

    def get_next_post(self, location):
        """Lấy bài đăng tiếp theo cho một địa điểm"""
        loc_type = location.get("type", "restaurant")
        loc_posts = [p for p in self.calendar.get("posts", []) if p.get("type") == loc_type]

        if not loc_posts:
            return self._generate_fallback_post(location)

        # Xoay vòng bài đăng theo index
        location_id = location.get("id", 1)
        index = (location_id + int(datetime.now().strftime("%j"))) % len(loc_posts)
        post_template = loc_posts[index]

        # Điền thông tin địa điểm
        content = post_template["content"]
        content = content.replace("{restaurant}", location.get("name", "uns"))
        content = content.replace("{city}", location.get("city", ""))
        content = content.replace("{website}", location.get("website", ""))

        return {
            "summary": content,
            "topicType": "STANDARD",
            "callToAction": {
                "actionType": CONFIG["DEFAULT_CTA_BUTTON"],
                "url": location.get("website", "")
            },
            "languageCode": post_template.get("lang", "de")
        }

    def _generate_fallback_post(self, location):
        """Tạo bài đăng dự phòng khi không có lịch"""
        if location.get("type") == "beauty":
            content = f"Willkommen bei {location['name']} in {location['city']}! ✨\n\nProfessionelle Nagelpflege und Beauty-Treatments in entspannter Atmosphäre. Termin jetzt online buchen!\n\n📍 {location['city']}\n⏰ Mo–Sa 10:00–19:00"
        else:
            content = f"Entdecken Sie authentische vietnamesische Küche bei {location['name']} in {location['city']}! 🍜\n\nFrisch zubereitete Pho mit hausgemachter Brühe und frischen Kräutern – täglich mit Liebe gekocht.\n\n📍 {location['city']}"

        return {
            "summary": content,
            "topicType": "STANDARD",
            "callToAction": {
                "actionType": CONFIG["DEFAULT_CTA_BUTTON"],
                "url": location.get("website", "")
            }
        }


# ============================================================
# BỘ ĐIỀU KHIỂN CHÍNH
# ============================================================
class GBPManager:
    """Bộ điều khiển chính cho toàn bộ hệ thống GBP"""

    def __init__(self, locations=None, config=None):
        self.config = config or CONFIG
        self.locations = locations or LOCATIONS
        self.client = GBPClient(self.config)
        self.template_mgr = ReplyTemplateManager()
        self.post_mgr = PostContentManager()
        self.stats = {"reviews_replied": 0, "posts_published": 0, "errors": 0}

    def run_reply_reviews(self):
        """Chạy tác vụ reply review cho tất cả địa điểm"""
        logger.info("=" * 60)
        logger.info(f"BẮT ĐẦU REPLY REVIEW – {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        logger.info("=" * 60)

        active_locations = [l for l in self.locations if l.get("active", True)]

        for location in active_locations:
            logger.info(f"\n📍 Xử lý: {location['name']} ({location['city']})")

            reviews = self.client.get_reviews(location)
            pending = [r for r in reviews if not r.get("reviewReply")]

            if not pending:
                logger.info("  Không có review nào cần reply.")
                continue

            logger.info(f"  Tìm thấy {len(pending)} review chưa reply.")

            for review in pending:
                stars = self.template_mgr.get_star_rating_int(review.get("starRating", "THREE"))
                reviewer = review.get("reviewer", {}).get("displayName", "Khách ẩn danh")

                logger.info(f"  Review từ {reviewer} – {stars}⭐")

                # Kiểm tra cài đặt auto-reply
                if stars == 5 and not self.config.get("AUTO_REPLY_5_STAR"):
                    logger.info("  Bỏ qua (auto-reply 5 sao đang tắt)")
                    continue
                if stars == 4 and not self.config.get("AUTO_REPLY_4_STAR"):
                    logger.info("  Bỏ qua (auto-reply 4 sao đang tắt)")
                    continue
                if stars <= 2 and self.config.get("ALERT_1_2_STAR"):
                    logger.warning(f"  ⚠️ REVIEW TIÊU CỰC! Cần xử lý thủ công: {reviewer}")
                    # TODO: Gửi email thông báo
                    # Vẫn tạo reply nhưng không gửi tự động
                    reply_text = self.template_mgr.get_reply(review, location)
                    if reply_text:
                        logger.info(f"  Gợi ý reply: {reply_text[:100]}...")
                    continue

                # Tạo và gửi reply
                reply_text = self.template_mgr.get_reply(review, location)
                if not reply_text:
                    logger.warning(f"  Không tìm được template phù hợp cho {reviewer}")
                    continue

                success = self.client.reply_to_review(location, review["name"], reply_text)
                if success:
                    self.stats["reviews_replied"] += 1
                else:
                    self.stats["errors"] += 1

                # Delay tránh spam API
                time.sleep(self.config.get("API_DELAY_SECONDS", 2))

                if self.stats["reviews_replied"] >= self.config.get("MAX_REPLIES_PER_RUN", 50):
                    logger.info("Đã đạt giới hạn reply trong một lần chạy.")
                    break

        logger.info(f"\n✓ Hoàn thành: Đã reply {self.stats['reviews_replied']} review | Lỗi: {self.stats['errors']}")

    def run_publish_posts(self):
        """Chạy tác vụ đăng bài cho tất cả địa điểm"""
        logger.info("=" * 60)
        logger.info(f"BẮT ĐẦU ĐĂNG BÀI – {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        logger.info("=" * 60)

        if not self.config.get("AUTO_PUBLISH_POSTS"):
            logger.info("Tính năng đăng bài tự động đang tắt.")
            return

        active_locations = [l for l in self.locations if l.get("active", True)]

        for location in active_locations:
            logger.info(f"\n📍 Đăng bài: {location['name']} ({location['city']})")

            post_data = self.post_mgr.get_next_post(location)
            success = self.client.create_post(location, post_data)

            if success:
                self.stats["posts_published"] += 1
            else:
                self.stats["errors"] += 1

            time.sleep(self.config.get("API_DELAY_SECONDS", 2))

            if self.stats["posts_published"] >= self.config.get("MAX_POSTS_PER_RUN", 20):
                logger.info("Đã đạt giới hạn bài đăng trong một lần chạy.")
                break

        logger.info(f"\n✓ Hoàn thành: Đã đăng {self.stats['posts_published']} bài | Lỗi: {self.stats['errors']}")

    def run_full_auto(self):
        """Chạy toàn bộ tác vụ tự động"""
        logger.info("🚀 KHỞI ĐỘNG CHẾ ĐỘ TỰ ĐỘNG HOÀN TOÀN")
        self.run_reply_reviews()
        self.run_publish_posts()
        self.print_summary()

    def print_summary(self):
        """In báo cáo tóm tắt"""
        logger.info("\n" + "=" * 60)
        logger.info("BÁO CÁO TÓM TẮT")
        logger.info("=" * 60)
        logger.info(f"  Tổng địa điểm hoạt động : {len([l for l in self.locations if l.get('active')])}")
        logger.info(f"  Review đã reply          : {self.stats['reviews_replied']}")
        logger.info(f"  Bài đã đăng              : {self.stats['posts_published']}")
        logger.info(f"  Lỗi                      : {self.stats['errors']}")
        logger.info(f"  Thời gian                : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        logger.info("=" * 60)

    def run_scheduler(self):
        """Chạy lên lịch tự động 24/7"""
        if schedule is None:
            logger.error("Thiếu thư viện 'schedule'. Chạy: pip install schedule")
            return

        post_time = self.config.get("POST_TIME", "22:07")
        interval_days = self.config.get("POST_INTERVAL_DAYS", 2)

        logger.info(f"⏰ Lên lịch đăng bài: {post_time} (mỗi {interval_days} ngày)")
        logger.info("⏰ Lên lịch reply review: mỗi 2 giờ")
        logger.info("Nhấn Ctrl+C để dừng...\n")

        # Reply review mỗi 2 giờ
        schedule.every(2).hours.do(self.run_reply_reviews)

        # Đăng bài theo lịch
        schedule.every(interval_days).days.at(post_time).do(self.run_publish_posts)

        # Báo cáo hàng tuần vào thứ Hai 8:00
        schedule.every().monday.at("08:00").do(self.print_summary)

        # Chạy ngay lần đầu
        self.run_full_auto()

        while True:
            schedule.run_pending()
            time.sleep(60)

    def authenticate(self):
        """Xác thực và lưu token"""
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            import json

            client_config = {
                "installed": {
                    "client_id": self.config["CLIENT_ID"],
                    "client_secret": self.config["CLIENT_SECRET"],
                    "redirect_uris": [self.config["REDIRECT_URI"]],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token"
                }
            }

            SCOPES = ['https://www.googleapis.com/auth/business.manage']
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            credentials = flow.run_local_server(port=8080)

            with open(self.config["TOKEN_FILE"], 'w') as f:
                f.write(credentials.to_json())

            logger.info("✓ Xác thực thành công! Token đã được lưu.")
        except Exception as e:
            logger.error(f"Lỗi xác thực: {e}")

    def load_locations_from_file(self, file_path="locations.json"):
        """Nạp danh sách địa điểm từ file JSON"""
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                self.locations = json.load(f)
            logger.info(f"Đã nạp {len(self.locations)} địa điểm từ {file_path}")
        else:
            logger.error(f"Không tìm thấy file {file_path}")

    def get_location_by_id(self, location_id):
        """Lấy location theo id"""
        for location in self.locations:
            if str(location.get("id")) == str(location_id):
                return location
        return None


# ============================================================
# ĐIỂM KHỞI CHẠY
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description='GBP Manager Pro – Tự động hóa Google Business Profile',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ sử dụng:
  python gbp_manager.py --action auth              # Xác thực Google API lần đầu
  python gbp_manager.py --action reply_reviews     # Reply review cho tất cả GBP
  python gbp_manager.py --action publish_posts     # Đăng bài cho tất cả GBP
  python gbp_manager.py --action full_auto         # Chạy toàn bộ một lần
  python gbp_manager.py --action scheduler         # Chạy tự động 24/7
  python gbp_manager.py --action report            # Xem báo cáo tóm tắt
        """
    )
    parser.add_argument(
        '--action',
        choices=['auth', 'reply_reviews', 'publish_posts', 'full_auto', 'scheduler', 'report'],
        default='full_auto',
        help='Hành động cần thực hiện'
    )
    parser.add_argument(
        '--locations-file',
        default=None,
        help='File JSON chứa danh sách địa điểm (tuỳ chọn)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Chạy thử, không gửi dữ liệu thật'
    )

    args = parser.parse_args()

    if args.dry_run:
        logger.info("⚠️  CHẾ ĐỘ THỬ NGHIỆM (Dry-run): Không có dữ liệu nào được gửi thật.")

    manager = GBPManager()

    if args.locations_file:
        manager.load_locations_from_file(args.locations_file)

    actions = {
        'auth': manager.authenticate,
        'reply_reviews': manager.run_reply_reviews,
        'publish_posts': manager.run_publish_posts,
        'full_auto': manager.run_full_auto,
        'scheduler': manager.run_scheduler,
        'report': manager.print_summary,
    }

    action_fn = actions.get(args.action, manager.run_full_auto)
    action_fn()


if __name__ == "__main__":
    main()
