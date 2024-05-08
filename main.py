import json
import os.path
import random
import sqlite3
import asyncio
from pathlib import Path

import requests
import threading
import instagrapi
from enum import Enum

from instagrapi.exceptions import LoginRequired, TwoFactorRequired
from telebot import TeleBot, custom_filters, types
from telebot.handler_backends import State, StatesGroup
from telebot.storage import StateMemoryStorage
from douyin_tiktok_scraper.scraper import Scraper

from tg_utils import build_markup
from datetime import datetime, timedelta, timezone

proxy = "прокси"
token = 'токен'
db = sqlite3.Connection("Posts.db", check_same_thread=False)

tiktok_api = Scraper()
tiktok_api.proxies = proxy
state_storage = StateMemoryStorage()
bot = TeleBot(token, state_storage=state_storage)
bot.add_custom_filter(custom_filters.StateFilter(bot))

admins = [1737227326]


def log(message) -> list[types.Message]:
    print(message)

    resp = []
    for adminId in admins:
        resp.append(bot.send_message(adminId, message))

    return resp


class States(StatesGroup):
    start = State()
    reels_waiting = State()
    story_waiting = State()
    only_reels = State()
    only_story = State()
    under_consideration = State()


class PostType(Enum):
    Reels = 1
    Story = 2


class SocType(Enum):
    Instagram = 1
    TikTok = 2
    Telegram = 3


class SocAccount:
    name: str

    ig_login: str
    ig_pass: str
    ig_client = None

    reels_schedule: list[int]
    story_schedule: list[int]
    post_schedule: list[int]

    reels_post_time: datetime
    story_post_time: datetime

    def __init__(self, name: str):
        self.name = name

        self.ig_login = db.execute(f'SELECT Login FROM IgAccounts WHERE Name Is "{name}"').fetchone()[0]
        self.ig_pass = db.execute(f'SELECT Password FROM IgAccounts WHERE Name Is "{name}"').fetchone()[0]

        self.reels_schedule = list(map(int, str(
            db.execute(f'SELECT ReelsScheldue FROM IgAccounts WHERE Name Is "{name}"').fetchone()[0]).split(' ')))
        self.story_schedule = list(map(int, str(
            db.execute(f'SELECT StoryScheldue FROM IgAccounts WHERE Name Is "{name}"').fetchone()[0]).split(' ')))

        self.reels_post_time = self.get_closest_time(self.reels_schedule)
        self.story_post_time = self.get_closest_time(self.story_schedule)

        self._ig_auth()

    def _ask_admin_for_2fa(self):
        log(f"Введи код для 2FA авторизации в {self.name}")
        for admin in admins:
            bot.register_next_step_handler_by_chat_id(admin, lambda msg: self._handle_ig_2fa(msg))

    def _ig_auth(self):
        session_path = Path(f"IgSessions/{self.name}.json")

        if os.path.exists(session_path):
            try:
                client = instagrapi.Client(delay_range=[1, 3], proxy=proxy)
                client.load_settings(session_path)
                client.login(self.ig_login, self.ig_pass)

                # check if session is valid
                try:
                    client.get_timeline_feed()
                    client.dump_settings(session_path)
                except LoginRequired:
                    self._ask_admin_for_2fa()

                self.ig_client = client
            except Exception as e:
                if type(e) == instagrapi.exceptions.TwoFactorRequired:
                    self._ask_admin_for_2fa()
                else:
                    print(type(e))
                    log(f"Ошибка входа в {self.name}, {e}")
        else:
            self._ask_admin_for_2fa()

    def _ig_auth_2fa(self, verification_code: str):
        try:
            client = instagrapi.Client(delay_range=[1, 3], proxy="http://adgolminer8:Dvap6jQSgI@85.239.145.213:51523")
            client.login(self.ig_login, self.ig_pass, verification_code=verification_code)
            client.dump_settings(f"IgSessions/{self.name}.json")

            self.ig_client = client
            log(f"Вошёл в {self.name}")
        except Exception as e:
            log(f"Ошибка входа в {self.name}, {e}")

    def _handle_ig_2fa(self, msg: types.Message):
        for admin in admins:
            bot.clear_step_handler_by_chat_id(admin)
        self._ig_auth_2fa(msg.text)

    def need_post_something(self) -> PostType | None:
        now = datetime.now(timezone.utc)

        if now >= self.reels_post_time:
            return PostType.Reels
        elif now >= self.story_post_time:
            return PostType.Story

        return None

    def post_reels(self):
        video_info = db.execute(f"SELECT UniqueId,UsedBy FROM Reels WHERE UsedBy IS NOT \"{self.name}\"").fetchone()
        print(self.ig_client.account_info())
        file_path = Path(os.getcwd(), "Reels", f"{video_info[0]}.mp4")

        if file_path.is_file():
            video_upload_resp = self.ig_client.clip_upload(file_path, "")

            self.ig_client.media_seen([video_upload_resp.id])
            self.ig_client.media_like(video_upload_resp.id)

            if video_info[1] is None and random.randint(0, 10) <= 3:
                cursor = db.cursor()
                cursor.execute(f"UPDATE Reels SET UsedBy=\"{self.name}\" WHERE UniqueId=\"{video_info[0]}\"")
                db.commit()
            else:
                # os.remove(file_path)
                cursor = db.cursor()
                cursor.execute(f"DELETE FROM Reels WHERE UniqueId=\"{video_info[0]}\"")
                db.commit()

            self.reels_post_time = self.get_closest_time(self.reels_schedule)

            log(f"Загрузил Reels в {self.name}, {video_upload_resp.video_url}")
        else:
            cursor = db.cursor()
            cursor.execute(f"DELETE FROM Reels WHERE UniqueId=\"{video_info[0]}\"")
            db.commit()

    def post_story(self):
        video_info = db.execute(f"SELECT UniqueId,UsedBy FROM Story WHERE UsedBy IS NOT \"{self.name}\"").fetchone()

        file_path = Path(os.getcwd(), "Story", f"{video_info[0]}.mp4")

        if file_path.is_file():
            video_upload_resp = self.ig_client.video_upload_to_story(file_path)

            self.ig_client.story_seen([int(video_upload_resp.pk)])
            # self.ig_client.story_like(video_upload_resp.id)

            if video_info[1] is None and random.randint(0, 10) <= 4:
                cursor = db.cursor()
                cursor.execute(f"UPDATE Story SET UsedBy=\"{self.name}\" WHERE UniqueId=\"{video_info[0]}\"")
                db.commit()
            else:
                # os.remove(file_path)
                cursor = db.cursor()
                cursor.execute(f"DELETE FROM Story WHERE UniqueId=\"{video_info[0]}\"")
                db.commit()

            self.story_post_time = self.get_closest_time(self.story_schedule)

            log(f"Загрузил Story в {self.name}, {video_upload_resp.video_url}")
        else:
            cursor = db.cursor()
            cursor.execute(f"DELETE FROM Reels WHERE UniqueId=\"{video_info[0]}\"")
            db.commit()

    def post_post(self):
        pass

    @staticmethod
    def get_closest_time(schedule) -> datetime:
        now = datetime.now(timezone.utc)
        start_posting = 7
        end_posting = 20

        hour = now.hour
        if hour > end_posting or (hour == end_posting and now.minute > 0):
            return (now + timedelta(days=1)).replace(hour=start_posting, minute=0, second=0, microsecond=0)
        elif hour < start_posting:
            return now.replace(hour=start_posting, minute=0, second=0, microsecond=0)

        day_of_week = now.weekday()
        interval_hours = (end_posting - start_posting) / schedule[day_of_week]
        interval = timedelta(hours=interval_hours)
        new_time = now.replace(hour=start_posting, minute=0, second=0, microsecond=0)
        while new_time <= now:
            new_time += interval
            hour = new_time.hour
            if hour > end_posting or (hour == end_posting and new_time.minute > 0):
                return (now + timedelta(days=1)).replace(hour=start_posting, minute=0, second=0, microsecond=0)
            elif hour < start_posting:
                return now.replace(hour=start_posting, minute=0, second=0, microsecond=0)

        return new_time


soc_accounts = [SocAccount("Magic 4ish"), SocAccount("Happy 4ish")]


# Commands first
@bot.message_handler(commands=['allto'])
def all_to(msg):
    markup = build_markup([[("Рилсы", "OnlyReels"), ("Истории", "OnlyStory")], [("Отмена", "Cancel")]])

    resp = bot.send_message(msg.chat.id,
                            "Режим All to\n\nВыбери в какую категорию мне загружать все видео которые ты будешь отпраавлять",
                            reply_markup=markup)
    set_new_action(resp.chat.id, resp.message_id)


@bot.message_handler(commands=['count'])
def post_time(msg):
    bot.send_message(msg.chat.id,
                     f"У нас в копилке:\n\n{get_post_count(PostType.Reels)} - Рилсов\n{get_post_count(PostType.Story)} - Сторис")


@bot.message_handler(commands=['post-time'])
def post_time(msg):
    resp = "Время ближайших постов:"
    for acc in soc_accounts:
        resp += f"\n\n{acc.name}:\nРилс - {acc.reels_post_time.strftime('%H:%M')}\nСторис - {acc.story_post_time.strftime('%H:%M')}\nПост - 0"

    bot.send_message(msg.chat.id, resp)


# @bot.message_handler(commands=['likeall'])
# def like_all(msg):
#     for acc in soc_accounts:
#         for


# States handling second
@bot.message_handler(state=States.only_reels, content_types=['text', 'video'])
def allto_reels(msg):
    if msg.content_type == 'video' or "tiktok.com" in msg.text or "instagram.com" in msg.text:
        process_video(msg, PostType.Reels, bot.send_message(msg.chat.id, "Обрабатываю...").message_id)


@bot.message_handler(state=States.only_story, content_types=['text', 'video'])
def allto_story(msg):
    if msg.content_type == 'video' or "tiktok.com" in msg.text or "instagram.com" in msg.text:
        process_video(msg, PostType.Reels, bot.send_message(msg.chat.id, "Обрабатываю...").message_id)


@bot.message_handler(state=States.reels_waiting, content_types=['text', 'video'])
def handle_reels(msg):
    if msg.content_type == 'video' or "tiktok.com" in msg.text or "instagram.com" in msg.text:
        set_new_action(msg.chat.id, None)
        bot.set_state(msg.chat.id, States.start)
        process_video(msg, PostType.Reels, bot.send_message(msg.chat.id, "Обрабатываю...").message_id)


@bot.message_handler(state=States.story_waiting, content_types=['text', 'video'])
def handle_story(msg):
    if msg.content_type == 'video' or "tiktok.com" in msg.text or "instagram.com" in msg.text:
        set_new_action(msg.chat.id, None)
        bot.set_state(msg.chat.id, States.start)
        process_video(msg, PostType.Story, bot.send_message(msg.chat.id, "Обрабатываю...").message_id)


# No state receiving
@bot.message_handler(content_types=["text", "video"])
def fast_handler(msg):
    markup = build_markup(
        [[("Рилс", "Reels"), ("История", "Story")], [("Отмена", "Cancel")]])
    if msg.content_type == 'video' or "tiktok.com" in msg.text or "instagram.com" in msg.text:
        bot.set_state(msg.from_user.id, States.under_consideration)

        with bot.retrieve_data(msg.from_user.id) as data:
            data['under_consideration'] = msg

        set_new_action(msg.from_user.id, bot.send_message(msg.chat.id, "Что это?", reply_markup=markup).message_id)
    else:
        new_action_msg = bot.send_message(msg.chat.id, "Что ты хочешь добавить?", reply_markup=markup)
        set_new_action(msg.chat.id, new_action_msg.message_id)


# Callbacks
@bot.callback_query_handler(func=lambda call: True)
def callbacks_handler(cb):
    match cb.data:
        case "OnlyReels":
            bot.set_state(cb.from_user.id, States.only_reels)
            bot.edit_message_text("Хорошо, жду рилсы, ты можешь отправить видео или ссылку на тикток/рилс.",
                                  cb.message.chat.id, cb.message.message_id,
                                  reply_markup=build_markup([[("Отменить", "Cancel")]]))
        case "OnlyStory":
            bot.set_state(cb.from_user.id, States.only_story, cb.message.chat.id)
            bot.edit_message_text("Хорошо, жду сторисы, ты можешь отправить видео или ссылку на тикток/рилс.",
                                  cb.message.chat.id, cb.message.message_id,
                                  reply_markup=build_markup([[("Отменить", "Cancel")]]))

        case "Reels":
            if bot.get_state(cb.from_user.id) == States.under_consideration.name:
                bot.set_state(cb.from_user.id, States.start)
                set_new_action(cb.from_user.id, None, False)
                with bot.retrieve_data(cb.from_user.id) as data:
                    process_video(data['under_consideration'], PostType.Reels, cb.message.message_id)
            else:
                set_new_action(cb.from_user.id, cb.message.message_id, False)
                bot.set_state(cb.from_user.id, States.reels_waiting)

                bot.edit_message_text("Хорошо, жду рилс, ты можешь отправить видео или ссылку на тикток/рилс.",
                                      cb.message.chat.id, cb.message.message_id,
                                      reply_markup=build_markup([[("Отменить", "Cancel")]]))
        case "Story":
            if bot.get_state(cb.from_user.id) == States.under_consideration.name:
                bot.set_state(cb.from_user.id, States.start)
                set_new_action(cb.from_user.id, None, False)
                with bot.retrieve_data(cb.from_user.id) as data:
                    process_video(data['under_consideration'], PostType.Story, cb.message.message_id)
            else:
                bot.set_state(cb.from_user.id, States.story_waiting)
                set_new_action(cb.from_user.id, cb.message.message_id, False)

                bot.edit_message_text("Хорошо, жду сторис, ты можешь отправить видео или ссылку на тикток/рилс.",
                                      cb.message.chat.id, cb.message.message_id,
                                      reply_markup=build_markup([[("Отменить", "Cancel")]]))

        case "Cancel":
            bot.delete_message(cb.from_user.id, cb.message.message_id)
            set_new_action(cb.from_user.id, None, False)
            bot.set_state(cb.from_user.id, States.start)


def process_video(msg, post_type: PostType, log_msg_id):
    print(bot.get_state(msg.chat.id))
    bot.edit_message_text("Получаю информацию...", msg.chat.id, log_msg_id)

    if msg.content_type == 'video':
        file_info = bot.get_file(msg.video.file_id)

        uid = file_info.file_unique_id
        if exist_in_db(uid, post_type):
            bot.edit_message_text("Это видео уже есть в списке", msg.chat.id, log_msg_id)
            return

        bot.edit_message_text("Скачиваю...", msg.chat.id, log_msg_id)
        file = bot.download_file(file_info.file_path)
    elif "tiktok.com" in msg.text:
        video_info = asyncio.run(tiktok_api.hybrid_parsing(msg.text))

        uid = video_info["aweme_id"]

        if exist_in_db(uid, post_type):
            bot.edit_message_text("Это видео уже есть в списке", msg.chat.id, log_msg_id)
            return

        bot.edit_message_text("Скачиваю...", msg.chat.id, log_msg_id)
        print(video_info["video_data"]["nwm_video_url_HQ"])
        open(f"{post_type.name}/{uid}.txt", 'wb').write(json.dumps(video_info).encode(encoding="utf-8"))
        file = requests.get(video_info["video_data"]["nwm_video_url_HQ"]).content
    elif "instagram.com" in msg.text:
        client = soc_accounts[0].ig_client

        uid = client.media_pk_from_url(msg.text)
        if exist_in_db(uid, post_type):
            bot.edit_message_text("Это видео уже есть в списке", msg.chat.id, log_msg_id)
            return

        bot.edit_message_text("Скачиваю...", msg.chat.id, log_msg_id)
        file = requests.get(client.media_info(uid).video_url).content

    open(f"{post_type.name}/{uid}.mp4", 'wb').write(file)

    cursor = db.cursor()
    cursor.execute(f"INSERT INTO {post_type.name} (UniqueId) VALUES (\"{uid}\")")
    db.commit()

    bot.edit_message_text(f"{post_type.name} добавлен, в копилке {get_post_count(post_type)}", msg.chat.id, log_msg_id)
    print(bot.get_state(msg.chat.id))


def get_post_count(post_type: PostType) -> int:
    return int(db.execute(f"SELECT Count(*) FROM {post_type.name}").fetchone()[0])


def exist_in_db(uid, post_type: PostType) -> bool:
    return int(db.execute(f"SELECT count(Id) FROM {post_type.name} WHERE UniqueId=\"{uid}\"").fetchone()[0]) == 1


def set_new_action(chat_id, new_msg, delete_last=True):
    print(bot.get_state(chat_id))
    if bot.get_state(chat_id) is None:
        bot.set_state(chat_id, States.start)
        with bot.retrieve_data(chat_id) as data:
            if new_msg is not None:
                data['action_waiting_msg'] = new_msg
            return

    with bot.retrieve_data(chat_id) as data:
        if delete_last and 'action_waiting_msg' in data:
            bot.delete_message(chat_id, data['action_waiting_msg'])

        if new_msg is None:
            data.pop('action_waiting_msg', None)
        else:
            data['action_waiting_msg'] = new_msg


def infinity_poster():
    for account in soc_accounts:
        if account.ig_client is not None:
            match account.need_post_something():
                case PostType.Reels:
                    if get_post_count(PostType.Reels) > 0 and db.execute(
                            f"SELECT EXISTS(SELECT 1 UsedBy FROM Reels WHERE UsedBy IS NOT \"{account.name}\")").fetchone()[
                        0] != 0:
                        account.post_reels()
                case PostType.Story:
                    if get_post_count(PostType.Story) > 0 and db.execute(
                            f"SELECT EXISTS(SELECT 1 UsedBy FROM Story WHERE UsedBy IS NOT \"{account.name}\")").fetchone()[
                        0] != 0:
                        account.post_story()

    threading.Timer(random.randint(90, 480), infinity_poster).start()


infinity_poster()
bot.infinity_polling()
