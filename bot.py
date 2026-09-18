from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
import struct
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv


# ============================================================
# НАСТРОЙКИ
# ============================================================

load_dotenv(override=True)
TOKEN = os.getenv("DISCORD_TOKEN", "")
RCON_ENABLED = os.getenv("RCON_ENABLED", "0") == "1"
RCON_HOST = os.getenv("RCON_HOST", "")
RCON_PORT = int(os.getenv("RCON_PORT", "25575"))
RCON_PASSWORD = os.getenv("RCON_PASSWORD", "")
RCON_TIMEOUT_SECONDS = 10
WHITELIST_COMMAND = "whitelist add {nickname}"
BAN_COMMAND = "ban {nickname} {reason}"
UNBAN_COMMAND = "unban {nickname}"
TEMPMUTE_COMMAND = "tempmute {nickname} {duration} {reason}"
UNMUTE_COMMAND = "unmute {nickname}"
WARN_COMMAND = "warn {nickname} {reason}"
UNWARN_COMMAND = "unwarn {nickname}"

APPLICATION_PANEL_CHANNEL_ID = 1486337529954304080
HELP_PANEL_CHANNEL_ID = 1495766775734865930
APPLICATION_CATEGORY_ID = 1500023409952686190
TICKET_CATEGORY_ID = 1485653736335605841
SPAM_PROTECTION_CHANNEL_ID = 1485655876193882363
LOG_CHANNEL_ID = 1486338493029548094
DOCUMENTATION_CHANNEL_ID = 1550499602040487996
DOCUMENTATION_MESSAGE_ID = 1550502972847558701
VOICE_CREATOR_CHANNEL_ID = 1498318412080746556
VOICE_CATEGORY_ID = 1485288483881746623
GUEST_ROLE_ID = 1485642937860620518
PLAYER_ROLE_ID = 1485642979556327445
HELPER_ROLE_ID = 1486339038402183338
ADMIN_ROLE_ID = 1486338979300380753
GUILD_ID = 1484230925473546292
RULES_CHANNEL_ID = 1485511848081227827
EVENTS_CHANNEL_ID = 1485637955677716683
EVENTS_ROLE_ID = 1520705428802109621
BAN_ROLE_ID = 1519084712210071552
STATISTICS_IP_NAME = "IP: amberland.pro"
STATISTICS_MEMBERS_PREFIX = "Участников:"
STATISTICS_PLAYERS_PREFIX = "Игроков:"
STATISTICS_ONLINE_PREFIX = "Онлайн:"
STATISTICS_UPDATE_DELAY_SECONDS = 30
MOSCOW_TIMEZONE = ZoneInfo("Europe/Moscow")

GOLD_EMBED_COLOR_HTML = "#F1C40F"
APPLICATION_PANEL_COLOR_HTML = GOLD_EMBED_COLOR_HTML
APPLICATION_EMBED_COLOR_HTML = GOLD_EMBED_COLOR_HTML
HELP_PANEL_COLOR_HTML = GOLD_EMBED_COLOR_HTML
TICKET_EMBED_COLOR_HTML = GOLD_EMBED_COLOR_HTML
VOICE_CONTROL_COLOR_HTML = GOLD_EMBED_COLOR_HTML
SPAM_WARNING_COLOR_HTML = "#ED4245"
APPLICATION_REJECTED_COLOR_HTML = "#ED4245"
APPLICATION_ACCEPTED_COLOR_HTML = "#57F287"
LOG_EMBED_COLOR_HTML = "#5865F2"

DB_FILE = "bot_state.sqlite3"
APP_PREFIX = "application_owner="
EVENT_PREFIX = "event_owner="
TICKET_PREFIX = "ticket_owner="
TICKET_CHANNEL_PREFIXES = {
    "bug": "баг",
    "login": "вход",
    "game": "игра",
    "player": "жалоба",
    "admin": "жалоба",
    "territory": "приват",
    "donation": "донат",
    "event": "ивент",
    "appeal": "апелляция",
    "other": "другое",
}
MODERATION_ROLE_NAMES = {
    "ban": "Бан",
    "mute": "Мут",
    "warn1": "Пред 1",
    "warn2": "Пред 2",
    "warn3": "Пред 3",
}
WARNING_LIFETIME_SECONDS = 3 * 24 * 60 * 60
PUNISHMENT_HISTORY_SECONDS = 30 * 24 * 60 * 60


# ============================================================
# ХРАНИЛИЩЕ
# ============================================================


class Store:
    def __init__(self) -> None:
        self.db = sqlite3.connect(DB_FILE)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS members (guild_id INTEGER, user_id INTEGER, PRIMARY KEY(guild_id,user_id));"
            "CREATE TABLE IF NOT EXISTS voices (voice_id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, closed INTEGER NOT NULL DEFAULT 0);"
            "CREATE TABLE IF NOT EXISTS applications (channel_id INTEGER PRIMARY KEY, nickname TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS player_links ("
            "guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, nickname TEXT NOT NULL COLLATE NOCASE, "
            "PRIMARY KEY(guild_id,user_id), UNIQUE(guild_id,nickname));"
            "CREATE TABLE IF NOT EXISTS punishments ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, "
            "kind TEXT NOT NULL, moderator_id INTEGER, reason TEXT NOT NULL, created_at INTEGER NOT NULL, "
            "expires_at INTEGER, active INTEGER NOT NULL DEFAULT 0);"
            "CREATE INDEX IF NOT EXISTS punishments_user_time ON punishments(guild_id,user_id,created_at);"
            "CREATE INDEX IF NOT EXISTS punishments_expiry ON punishments(active,expires_at);"
            "CREATE TABLE IF NOT EXISTS mute_overwrites ("
            "guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, "
            "allow_value TEXT NOT NULL, deny_value TEXT NOT NULL, "
            "PRIMARY KEY(guild_id,user_id,channel_id));"
            "CREATE TABLE IF NOT EXISTS ticket_assignments ("
            "channel_id INTEGER PRIMARY KEY, assignee_id INTEGER NOT NULL);"
            "CREATE TABLE IF NOT EXISTS daily_metrics ("
            "day TEXT NOT NULL, key TEXT NOT NULL, value INTEGER NOT NULL DEFAULT 0, "
            "PRIMARY KEY(day,key));"
        )
        self.db.commit()

    def get(self, key: str) -> int | None:
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return int(row[0]) if row else None

    def set(self, key: str, value: int) -> None:
        self.db.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
        self.db.commit()

    def first_join(self, guild_id: int, user_id: int) -> bool:
        cursor = self.db.execute("INSERT OR IGNORE INTO members VALUES(?,?)", (guild_id, user_id))
        self.db.commit()
        return cursor.rowcount == 1

    def add_application(self, channel_id: int, nickname: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO applications VALUES(?,?)", (channel_id, nickname))
        self.db.commit()

    def application_nickname(self, channel_id: int) -> str | None:
        row = self.db.execute("SELECT nickname FROM applications WHERE channel_id=?", (channel_id,)).fetchone()
        return str(row[0]) if row else None

    def remove_application(self, channel_id: int) -> None:
        self.db.execute("DELETE FROM applications WHERE channel_id=?", (channel_id,))
        self.db.commit()

    def set_player_nickname(self, guild_id: int, user_id: int, nickname: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO player_links(guild_id,user_id,nickname) VALUES(?,?,?) "
                "ON CONFLICT(guild_id,user_id) DO UPDATE SET nickname=excluded.nickname",
                (guild_id, user_id, nickname),
            )

    def player_nickname(self, guild_id: int, user_id: int) -> str | None:
        row = self.db.execute(
            "SELECT nickname FROM player_links WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        ).fetchone()
        return str(row[0]) if row else None

    def player_for_nickname(self, guild_id: int, nickname: str) -> int | None:
        row = self.db.execute(
            "SELECT user_id FROM player_links WHERE guild_id=? AND nickname=? COLLATE NOCASE",
            (guild_id, nickname),
        ).fetchone()
        return int(row[0]) if row else None

    def add_voice(self, voice_id: int, owner_id: int) -> None:
        self.db.execute("INSERT OR REPLACE INTO voices VALUES(?,?,0)", (voice_id, owner_id))
        self.db.commit()

    def close_voice(self, voice_id: int, closed: bool) -> None:
        self.db.execute("UPDATE voices SET closed=? WHERE voice_id=?", (int(closed), voice_id))
        self.db.commit()

    def remove_voice(self, voice_id: int) -> None:
        self.db.execute("DELETE FROM voices WHERE voice_id=?", (voice_id,))
        self.db.commit()

    def voices(self) -> list[tuple[int, int, bool]]:
        return [(voice_id, owner_id, bool(closed)) for voice_id, owner_id, closed in self.db.execute("SELECT voice_id,owner_id,closed FROM voices")]

    def add_punishment(
        self,
        guild_id: int,
        user_id: int,
        kind: str,
        moderator_id: int | None,
        reason: str,
        *,
        expires_at: int | None = None,
        active: bool = False,
        created_at: int | None = None,
    ) -> int:
        cursor = self.db.execute(
            "INSERT INTO punishments(guild_id,user_id,kind,moderator_id,reason,created_at,expires_at,active) VALUES(?,?,?,?,?,?,?,?)",
            (guild_id, user_id, kind, moderator_id, reason, created_at or int(datetime.now(timezone.utc).timestamp()), expires_at, int(active)),
        )
        self.db.commit()
        return int(cursor.lastrowid)

    def active_punishments(self, guild_id: int, user_id: int, kind: str | None = None) -> list[sqlite3.Row]:
        if kind is None:
            return list(self.db.execute(
                "SELECT * FROM punishments WHERE guild_id=? AND user_id=? AND active=1 ORDER BY created_at,id",
                (guild_id, user_id),
            ))
        return list(self.db.execute(
            "SELECT * FROM punishments WHERE guild_id=? AND user_id=? AND kind=? AND active=1 ORDER BY created_at,id",
            (guild_id, user_id, kind),
        ))

    def active_count(self, guild_id: int, user_id: int, kind: str) -> int:
        row = self.db.execute(
            "SELECT COUNT(*) FROM punishments WHERE guild_id=? AND user_id=? AND kind=? AND active=1",
            (guild_id, user_id, kind),
        ).fetchone()
        return int(row[0])

    def deactivate(self, punishment_id: int) -> None:
        self.db.execute("UPDATE punishments SET active=0 WHERE id=?", (punishment_id,))
        self.db.commit()

    def activate(self, punishment_id: int) -> None:
        self.db.execute("UPDATE punishments SET active=1 WHERE id=?", (punishment_id,))
        self.db.commit()

    def deactivate_all(self, guild_id: int, user_id: int, kind: str) -> list[sqlite3.Row]:
        rows = self.active_punishments(guild_id, user_id, kind)
        if rows:
            self.db.executemany("UPDATE punishments SET active=0 WHERE id=?", ((row["id"],) for row in rows))
            self.db.commit()
        return rows

    def deactivate_latest_warning(self, guild_id: int, user_id: int) -> sqlite3.Row | None:
        row = self.db.execute(
            "SELECT * FROM punishments WHERE guild_id=? AND user_id=? AND kind='warn' AND active=1 ORDER BY created_at DESC,id DESC LIMIT 1",
            (guild_id, user_id),
        ).fetchone()
        if row:
            self.deactivate(int(row["id"]))
        return row

    def expired_punishments(self, guild_id: int, now: int) -> list[sqlite3.Row]:
        return list(self.db.execute(
            "SELECT * FROM punishments WHERE guild_id=? AND active=1 AND expires_at IS NOT NULL AND expires_at<=? ORDER BY expires_at,id",
            (guild_id, now),
        ))

    def punishment_history(self, guild_id: int, user_id: int, since: int) -> list[sqlite3.Row]:
        return list(self.db.execute(
            "SELECT * FROM punishments WHERE guild_id=? AND user_id=? AND created_at>=? ORDER BY created_at DESC,id DESC",
            (guild_id, user_id, since),
        ))

    def punishment_user_ids(self, guild_id: int) -> list[int]:
        return [int(row[0]) for row in self.db.execute(
            "SELECT DISTINCT user_id FROM punishments WHERE guild_id=? AND active=1",
            (guild_id,),
        )]

    def active_user_ids(self, guild_id: int, kind: str) -> list[int]:
        return [int(row[0]) for row in self.db.execute(
            "SELECT DISTINCT user_id FROM punishments WHERE guild_id=? AND kind=? AND active=1",
            (guild_id, kind),
        )]

    def save_mute_overwrite(self, guild_id: int, user_id: int, channel_id: int, allow_value: int, deny_value: int) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO mute_overwrites(guild_id,user_id,channel_id,allow_value,deny_value) VALUES(?,?,?,?,?)",
            (guild_id, user_id, channel_id, str(allow_value), str(deny_value)),
        )
        self.db.commit()

    def mute_overwrites(self, guild_id: int, user_id: int) -> list[sqlite3.Row]:
        return list(self.db.execute(
            "SELECT * FROM mute_overwrites WHERE guild_id=? AND user_id=? ORDER BY channel_id",
            (guild_id, user_id),
        ))

    def remove_mute_overwrite(self, guild_id: int, user_id: int, channel_id: int) -> None:
        self.db.execute(
            "DELETE FROM mute_overwrites WHERE guild_id=? AND user_id=? AND channel_id=?",
            (guild_id, user_id, channel_id),
        )
        self.db.commit()

    def purge_old_punishments(self, before: int) -> None:
        self.db.execute("DELETE FROM punishments WHERE active=0 AND created_at<?", (before,))
        self.db.commit()

    def ticket_assignee(self, channel_id: int) -> int | None:
        row = self.db.execute(
            "SELECT assignee_id FROM ticket_assignments WHERE channel_id=?",
            (channel_id,),
        ).fetchone()
        return int(row[0]) if row else None

    def remove_ticket_assignment(self, channel_id: int) -> None:
        self.db.execute("DELETE FROM ticket_assignments WHERE channel_id=?", (channel_id,))
        self.db.commit()

    def increment_daily_metric(self, key: str, amount: int = 1, *, day: date | None = None) -> None:
        metric_day = (day or datetime.now(MOSCOW_TIMEZONE).date()).isoformat()
        self.db.execute(
            "INSERT INTO daily_metrics(day,key,value) VALUES(?,?,?) "
            "ON CONFLICT(day,key) DO UPDATE SET value=value+excluded.value",
            (metric_day, key, amount),
        )
        self.db.commit()

    def update_daily_maximum(self, key: str, value: int, *, day: date | None = None) -> None:
        metric_day = (day or datetime.now(MOSCOW_TIMEZONE).date()).isoformat()
        self.db.execute(
            "INSERT INTO daily_metrics(day,key,value) VALUES(?,?,?) "
            "ON CONFLICT(day,key) DO UPDATE SET value=MAX(value,excluded.value)",
            (metric_day, key, value),
        )
        self.db.commit()

    def daily_metrics(self, day: date) -> dict[str, int]:
        return {
            str(row[0]): int(row[1])
            for row in self.db.execute(
                "SELECT key,value FROM daily_metrics WHERE day=?",
                (day.isoformat(),),
            )
        }


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================


def owner(channel: discord.abc.GuildChannel, prefix: str) -> int | None:
    match = re.search(rf"{prefix}(\d+)", getattr(channel, "topic", "") or "")
    return int(match.group(1)) if match else None


def embed_details(message: discord.Message, title: str) -> dict[str, str]:
    for embed in message.embeds:
        if embed.title == title:
            return {field.name: field.value for field in embed.fields}
    return {}


async def application_nickname(channel: discord.TextChannel) -> str | None:
    nickname = bot.store.application_nickname(channel.id)
    if nickname:
        return nickname
    details = await application_details(channel)
    return details.get("Никнейм")


async def application_details(channel: discord.TextChannel) -> dict[str, str]:
    try:
        async for message in channel.history(limit=25, oldest_first=True):
            details = embed_details(message, "Новая заявка")
            if details:
                return details
    except discord.HTTPException:
        pass
    return {}


async def event_details(channel: discord.TextChannel) -> dict[str, str]:
    try:
        async for message in channel.history(limit=1000, oldest_first=True):
            details = embed_details(message, "Заявка на проведение ивента")
            if details:
                return details
    except discord.HTTPException:
        pass
    return {}


def is_image(attachment: discord.Attachment) -> bool:
    content_type = (attachment.content_type or "").lower()
    return content_type.startswith("image/") or attachment.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))


async def event_photos(channel: discord.TextChannel, user_id: int) -> list[discord.Attachment]:
    photos: list[discord.Attachment] = []
    try:
        async for message in channel.history(limit=1000, oldest_first=True):
            if message.author.id == user_id:
                photos.extend(attachment for attachment in message.attachments if is_image(attachment))
    except discord.HTTPException:
        logging.exception("Не удалось прочитать фотографии из заявки на ивент")
    return photos


def colour(html: str) -> discord.Colour:
    return discord.Colour(int(html.removeprefix("#"), 16))


def channel_name(prefix: str, member: discord.Member) -> str:
    name = re.sub(r"[^a-z0-9_-]", "", member.name.lower().replace(" ", "-"))
    return f"{prefix}-{name or member.id}"[:100]


class RconError(RuntimeError):
    pass


def rcon_packet(request_id: int, packet_type: int, payload: str) -> bytes:
    encoded_payload = payload.encode("utf-8")
    body = struct.pack("<ii", request_id, packet_type) + encoded_payload + b"\x00\x00"
    return struct.pack("<i", len(body)) + body


async def read_rcon_packet(reader: asyncio.StreamReader) -> tuple[int, int, str]:
    packet_length = struct.unpack("<i", await reader.readexactly(4))[0]
    if packet_length < 10 or packet_length > 4 * 1024 * 1024:
        raise RconError("RCON вернул пакет некорректного размера")

    body = await reader.readexactly(packet_length)
    if body[-2:] != b"\x00\x00":
        raise RconError("RCON вернул повреждённый пакет")

    request_id, packet_type = struct.unpack("<ii", body[:8])
    return request_id, packet_type, body[8:-2].decode("utf-8", errors="replace")


async def rcon_command(command: str) -> str:
    if not RCON_ENABLED or not RCON_HOST or not RCON_PASSWORD:
        logging.warning("RCON: команда не выполнена — подключение не настроено")
        bot.store.increment_daily_metric("rcon_errors")
        raise RconError("RCON не настроен")

    writer: asyncio.StreamWriter | None = None
    try:
        logging.info("RCON: подключение к серверу и отправка команды: %s", command)
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(RCON_HOST, RCON_PORT),
            timeout=RCON_TIMEOUT_SECONDS,
        )

        auth_id = 1
        writer.write(rcon_packet(auth_id, 3, RCON_PASSWORD))
        await asyncio.wait_for(writer.drain(), timeout=RCON_TIMEOUT_SECONDS)

        authenticated = False
        for _ in range(2):
            response_id, response_type, _ = await asyncio.wait_for(
                read_rcon_packet(reader),
                timeout=RCON_TIMEOUT_SECONDS,
            )
            if response_id == -1:
                logging.warning("RCON: сервер отклонил пароль")
                raise RconError("RCON отклонил пароль")
            if response_id == auth_id and response_type == 2:
                authenticated = True
                break
        if not authenticated:
            raise RconError("RCON вернул некорректный ответ при авторизации")

        command_id = 2
        writer.write(rcon_packet(command_id, 2, command))
        await asyncio.wait_for(writer.drain(), timeout=RCON_TIMEOUT_SECONDS)
        response_id, response_type, response = await asyncio.wait_for(
            read_rcon_packet(reader),
            timeout=RCON_TIMEOUT_SECONDS,
        )
        if response_id != command_id or response_type != 0:
            raise RconError("RCON вернул некорректный ответ на команду")

        logging.info("RCON: команда выполнена. Ответ сервера: %s", response or "без текстового ответа")
        return response
    except RconError:
        bot.store.increment_daily_metric("rcon_errors")
        raise
    except TimeoutError as error:
        logging.warning("RCON: сервер не ответил за %s секунд", RCON_TIMEOUT_SECONDS)
        bot.store.increment_daily_metric("rcon_errors")
        raise RconError("RCON не ответил вовремя") from error
    except ConnectionRefusedError as error:
        logging.warning("RCON: сервер отклонил подключение")
        bot.store.increment_daily_metric("rcon_errors")
        raise RconError("RCON отклонил подключение") from error
    except (OSError, asyncio.IncompleteReadError, struct.error) as error:
        logging.exception("RCON: не удалось выполнить команду")
        bot.store.increment_daily_metric("rcon_errors")
        raise RconError("Не удалось выполнить команду RCON") from error
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, RuntimeError):
                pass


async def whitelist_player(nickname: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", nickname):
        raise RconError("Никнейм не соответствует формату Minecraft")
    return await rcon_command(WHITELIST_COMMAND.format(nickname=nickname))


class Bot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.voice_states = True
        super().__init__(command_prefix="!", intents=intents)
        self.store = Store()
        self.started = False
        self.interaction_ids: set[int] = set()
        self.moderation_lock = asyncio.Lock()
        self.statistics_lock = asyncio.Lock()
        self.daily_summary_lock = asyncio.Lock()
        self.statistics_update_tasks: dict[int, asyncio.Task[None]] = {}
        self.automatic_bans: set[tuple[int, int]] = set()

    def claim_interaction(self, interaction_id: int) -> bool:
        if interaction_id in self.interaction_ids:
            return False
        self.interaction_ids.add(interaction_id)
        if len(self.interaction_ids) > 1000:
            self.interaction_ids.clear()
        return True

    async def roles(self, guild: discord.Guild) -> tuple[discord.Role, discord.Role, discord.Role, discord.Role]:
        roles = tuple(guild.get_role(role_id) for role_id in (GUEST_ROLE_ID, PLAYER_ROLE_ID, HELPER_ROLE_ID, ADMIN_ROLE_ID))
        if any(role is None for role in roles):
            raise RuntimeError("Не найдены одна или несколько ролей из настроек.")
        return roles

    async def log(
        self,
        guild: discord.Guild,
        action: str,
        fields: dict[str, object] | None = None,
        avatar_url: str | None = None,
        embed_color_html: str | None = None,
    ) -> None:
        logging.info("%s | %s", action, fields or {})
        channel = guild.get_channel(LOG_CHANNEL_ID)
        if isinstance(channel, discord.TextChannel):
            try:
                embed = discord.Embed(
                    title=f"Лог • {action}",
                    colour=colour(embed_color_html or LOG_EMBED_COLOR_HTML),
                    timestamp=datetime.now(timezone.utc),
                )
                if avatar_url:
                    embed.set_thumbnail(url=avatar_url)
                for name, value in (fields or {}).items():
                    text = str(value) or "Не указано"
                    parts = [text[index:index + 1024] for index in range(0, len(text), 1024)]
                    for index, part in enumerate(parts):
                        field_name = str(name) if index == 0 else f"{name} (продолжение {index + 1})"
                        embed.add_field(name=field_name[:256], value=part, inline=False)
                await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                logging.exception("Не удалось отправить лог")

    async def setup_hook(self) -> None:
        guild = discord.Object(id=GUILD_ID)
        await self.tree.sync(guild=guild)
        await self.tree.sync()
        if not punishment_expiry_loop.is_running():
            punishment_expiry_loop.start()
        if not statistics_refresh_loop.is_running():
            statistics_refresh_loop.start()
        if not daily_summary_loop.is_running():
            daily_summary_loop.start()

    async def on_ready(self) -> None:
        if self.started:
            return
        self.started = True
        for guild in self.guilds:
            try:
                await update_moderator_documentation(guild)
                await self.roles(guild)
                await setup_moderation(guild)
                await panels(guild)
                await restore(guild)
                await ensure_daily_summary(guild)
                logging.info("Бот запущен: сервер %s, панели и кнопки проверены.", guild.name)
            except Exception:
                logging.exception("Ошибка настройки сервера %s", guild.id)


bot = Bot()


async def staff(interaction: discord.Interaction) -> tuple[discord.Role, discord.Role, discord.Role, discord.Role] | None:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Это действие доступно только на сервере", ephemeral=True)
        return None
    roles = await bot.roles(interaction.guild)
    if not (interaction.user.guild_permissions.administrator or roles[2] in interaction.user.roles or roles[3] in interaction.user.roles):
        await interaction.response.send_message("Это действие доступно только хелперам и администраторам", ephemeral=True)
        return None
    return roles


async def dm(member: discord.Member, embed: discord.Embed) -> bool:
    try:
        await member.send(embed=embed)
        return True
    except discord.HTTPException:
        return False


async def show_modal(interaction: discord.Interaction, modal: discord.ui.Modal) -> None:
    if interaction.response.is_done() or not bot.claim_interaction(interaction.id):
        return
    try:
        await interaction.response.send_modal(modal)
    except discord.HTTPException as error:
        if error.code not in (10062, 40060):
            raise
        logging.warning("Пропущено повторное или устаревшее нажатие кнопки: %s", interaction.id)


async def moderation_roles(guild: discord.Guild) -> dict[str, discord.Role]:
    result: dict[str, discord.Role] = {}
    for key, name in MODERATION_ROLE_NAMES.items():
        if key == "ban":
            role = guild.get_role(BAN_ROLE_ID)
            if role is None:
                raise RuntimeError(f"Не найдена роль бана с ID {BAN_ROLE_ID}")
            result[key] = role
            continue
        role_id = bot.store.get(f"moderation_role:{guild.id}:{key}")
        role = guild.get_role(role_id) if role_id else None
        if role is None:
            role = discord.utils.get(guild.roles, name=name)
        if role is None:
            role = await guild.create_role(name=name, reason="Настройка системы модерации")
        bot.store.set(f"moderation_role:{guild.id}:{key}", role.id)
        result[key] = role
    return result


async def apply_mute_overwrite(channel: discord.abc.GuildChannel, mute_role: discord.Role) -> None:
    overwrite = channel.overwrites_for(mute_role)
    changed = False
    denied_permissions = (
        "send_messages",
        "send_messages_in_threads",
        "send_voice_messages",
        "create_public_threads",
        "create_private_threads",
        "add_reactions",
        "speak",
        "stream",
        "request_to_speak",
        "use_soundboard",
        "use_external_sounds",
    )
    for permission in denied_permissions:
        if permission in discord.Permissions.VALID_FLAGS and getattr(overwrite, permission) is not False:
            setattr(overwrite, permission, False)
            changed = True
    if changed:
        await channel.set_permissions(mute_role, overwrite=overwrite, reason="Настройка роли мута")


def is_appeal_channel_for(channel: discord.abc.GuildChannel, user_id: int) -> bool:
    return (
        isinstance(channel, discord.TextChannel)
        and owner(channel, TICKET_PREFIX) == user_id
        and (channel.topic or "").partition(";")[2] == "appeal"
    )


async def apply_member_mute_overwrite(channel: discord.abc.GuildChannel, member: discord.Member) -> bool:
    if is_appeal_channel_for(channel, member.id):
        return True
    denied_permissions = (
        "send_messages",
        "send_messages_in_threads",
        "send_voice_messages",
        "create_public_threads",
        "create_private_threads",
        "add_reactions",
        "speak",
        "stream",
        "request_to_speak",
        "use_soundboard",
        "use_external_sounds",
    )
    overwrite = channel.overwrites_for(member)
    allow, deny = overwrite.pair()
    bot.store.save_mute_overwrite(member.guild.id, member.id, channel.id, allow.value, deny.value)
    changed = False
    for permission in denied_permissions:
        if permission in discord.Permissions.VALID_FLAGS and getattr(overwrite, permission) is not False:
            setattr(overwrite, permission, False)
            changed = True
    if not changed:
        return True
    try:
        await channel.set_permissions(member, overwrite=overwrite, reason="Применение мута")
    except discord.HTTPException:
        logging.exception("Не удалось применить мут пользователю %s в канале %s", member.id, channel.id)
        return False
    return True


async def apply_member_mute_overwrites(member: discord.Member) -> int:
    failed = 0
    for channel in member.guild.channels:
        if not await apply_member_mute_overwrite(channel, member):
            failed += 1
    return failed


async def restore_member_mute_overwrites(member: discord.Member) -> int:
    failed = 0
    for row in bot.store.mute_overwrites(member.guild.id, member.id):
        channel = member.guild.get_channel(int(row["channel_id"]))
        if channel is None:
            bot.store.remove_mute_overwrite(member.guild.id, member.id, int(row["channel_id"]))
            continue
        allow = discord.Permissions(int(row["allow_value"]))
        deny = discord.Permissions(int(row["deny_value"]))
        overwrite = discord.PermissionOverwrite.from_pair(allow, deny)
        try:
            await channel.set_permissions(
                member,
                overwrite=overwrite if allow.value or deny.value else None,
                reason="Снятие мута",
            )
        except discord.HTTPException:
            failed += 1
            logging.exception("Не удалось восстановить права пользователя %s в канале %s", member.id, channel.id)
            continue
        bot.store.remove_mute_overwrite(member.guild.id, member.id, channel.id)
    return failed


async def sync_warning_roles(member: discord.Member, roles: dict[str, discord.Role]) -> int:
    count = min(bot.store.active_count(member.guild.id, member.id, "warn"), 3)
    warning_roles = [roles["warn1"], roles["warn2"], roles["warn3"]]
    desired = warning_roles[count - 1] if count else None
    to_remove = [role for role in warning_roles if role in member.roles and role != desired]
    if to_remove:
        await member.remove_roles(*to_remove, reason="Обновление количества предупреждений")
    if desired is not None and desired not in member.roles:
        await member.add_roles(desired, reason="Обновление количества предупреждений")
    return count


async def restore_member_punishments(member: discord.Member, roles: dict[str, discord.Role]) -> None:
    if bot.store.active_count(member.guild.id, member.id, "ban"):
        if roles["ban"] not in member.roles:
            await member.add_roles(roles["ban"], reason="Восстановление активного бана")
    elif roles["ban"] in member.roles:
        await member.remove_roles(roles["ban"], reason="Удаление неактуальной роли бана")
    if bot.store.active_count(member.guild.id, member.id, "mute"):
        if roles["mute"] not in member.roles:
            await member.add_roles(roles["mute"], reason="Восстановление активного мута")
        await apply_member_mute_overwrites(member)
    else:
        await restore_member_mute_overwrites(member)
    await sync_warning_roles(member, roles)


async def setup_moderation(guild: discord.Guild) -> None:
    async with bot.moderation_lock:
        roles = await moderation_roles(guild)
        for channel in guild.channels:
            try:
                await apply_mute_overwrite(channel, roles["mute"])
            except discord.HTTPException:
                logging.exception("Не удалось настроить роль мута в канале %s", channel.id)
        await process_expired_punishments(guild, roles)
        for user_id in bot.store.punishment_user_ids(guild.id):
            member = guild.get_member(user_id)
            if member is not None:
                try:
                    await restore_member_punishments(member, roles)
                except discord.HTTPException:
                    logging.exception("Не удалось восстановить наказания пользователя %s", user_id)


async def moderation_target(
    interaction: discord.Interaction,
    member: discord.Member,
) -> tuple[discord.Role, discord.Role, discord.Role, discord.Role] | None:
    roles = await staff(interaction)
    if not roles or not interaction.guild or not isinstance(interaction.user, discord.Member):
        return None
    bot_member = interaction.guild.me
    if member.id == interaction.user.id:
        await interaction.response.send_message("Нельзя выдать наказание самому себе", ephemeral=True)
        return None
    if member.bot:
        await interaction.response.send_message("Ботам нельзя выдавать наказания через эту систему", ephemeral=True)
        return None
    if member.id == interaction.guild.owner_id:
        await interaction.response.send_message("Владельцу сервера нельзя выдать это наказание", ephemeral=True)
        return None
    moderator_is_admin = interaction.user.guild_permissions.administrator or roles[3] in interaction.user.roles
    target_is_staff = member.guild_permissions.administrator or roles[2] in member.roles or roles[3] in member.roles
    if target_is_staff and not moderator_is_admin:
        await interaction.response.send_message(
            "Хелперы не могут наказывать хелперов или администраторов",
            ephemeral=True,
        )
        return None
    if bot_member is None or member.top_role >= bot_member.top_role:
        await interaction.response.send_message("Роль бота должна находиться выше роли этого пользователя", ephemeral=True)
        return None
    if interaction.user.id != interaction.guild.owner_id and member.top_role >= interaction.user.top_role:
        await interaction.response.send_message("Нельзя наказать пользователя с равной или более высокой ролью", ephemeral=True)
        return None
    return roles


def parse_duration(value: str) -> tuple[int, str, str] | None:
    match = re.fullmatch(r"([1-9]\d*)([мчд])", value.strip().lower())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    seconds_per_unit = {"м": 60, "ч": 60 * 60, "д": 24 * 60 * 60}
    unit_names = {"м": "мин.", "ч": "ч.", "д": "дн."}
    seconds = amount * seconds_per_unit[unit]
    if seconds > 10 * 365 * 24 * 60 * 60:
        return None
    rcon_units = {"м": "m", "ч": "h", "д": "d"}
    return seconds, f"{amount} {unit_names[unit]}", f"{amount}{rcon_units[unit]}"


def safe_rcon_reason(reason: str) -> str:
    cleaned = " ".join(reason.replace("\x00", " ").replace("\r", " ").replace("\n", " ").split())
    return cleaned[:500] or "Причина не указана"


def server_minecraft_nickname(member: discord.Member) -> str | None:
    nickname = member.nick
    if nickname and re.fullmatch(r"[A-Za-z0-9_]{3,16}", nickname):
        return nickname
    return None


async def require_player_nickname(interaction: discord.Interaction, member: discord.Member) -> str | None:
    if not interaction.guild:
        return None
    nickname = server_minecraft_nickname(member)
    if nickname is None:
        message = (
            "У пользователя не установлен корректный никнейм Minecraft на этом Discord-сервере. "
            "Серверный ник должен состоять из 3–16 латинских букв, цифр или символов `_`"
        )
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    return nickname


def capitalized_field_value(value: str) -> str:
    cleaned = value.strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else "Не указано"


def punishment_period(started_at: int, expires_at: int) -> str:
    return f"<t:{started_at}:f> — <t:{expires_at}:f>"


def punishment_embed(
    title: str,
    moderator: discord.Member | None,
    reason: str,
    *,
    duration: str | None = None,
    extra: str | None = None,
    appeal: bool = False,
) -> discord.Embed:
    lines = [
        f"**Причина:** {capitalized_field_value(reason)}",
        f"**Модератор:** {moderator.mention if moderator else 'Система'}",
    ]
    if duration:
        lines.insert(0, f"**Срок:** {capitalized_field_value(duration)}")
    if extra:
        lines.append(extra)
    if appeal:
        lines.append("Для обжалования наказания напишите модератору в личные сообщения")
    return discord.Embed(title=title, description="\n".join(lines), colour=colour(APPLICATION_REJECTED_COLOR_HTML), timestamp=datetime.now(timezone.utc))


async def log_punishment(
    guild: discord.Guild,
    action: str,
    user: discord.abc.User,
    moderator: discord.Member | None,
    reason: str,
    *,
    duration: str | None = None,
    colour_html: str = APPLICATION_REJECTED_COLOR_HTML,
    extra_fields: dict[str, object] | None = None,
) -> None:
    fields: dict[str, object] = {
        "Пользователь": f"{user.mention} ({user})",
        "Модератор": moderator.mention if moderator else "Система",
        "Причина": capitalized_field_value(reason),
    }
    if duration:
        fields["Срок"] = capitalized_field_value(duration)
    fields.update(extra_fields or {})
    await bot.log(
        guild,
        action,
        fields,
        avatar_url=str(user.display_avatar.url),
        embed_color_html=colour_html,
    )


async def panels(guild: discord.Guild) -> None:
    items = [
        ("application", APPLICATION_PANEL_CHANNEL_ID, discord.Embed(description="Хотите стать игроком? Нажмите кнопку ниже и заполните короткую заявку", colour=colour(APPLICATION_PANEL_COLOR_HTML)), ApplicationPanel()),
        ("help", HELP_PANEL_CHANNEL_ID, discord.Embed(description="Нужна помощь? Нажмите кнопку, выберите тему обращения и опишите ситуацию", colour=colour(HELP_PANEL_COLOR_HTML)), HelpPanel()),
        ("spam", SPAM_PROTECTION_CHANNEL_ID, discord.Embed(description="Писать в этом канале **категорически запрещено**. Любое сообщение здесь приведёт к автоматической блокировке на сервере", colour=colour(SPAM_WARNING_COLOR_HTML)), None),
    ]
    for key, channel_id, embed, view in items:
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            continue
        message_id = bot.store.get(f"{key}:{guild.id}")
        if message_id:
            try:
                message = await channel.fetch_message(message_id)
                if view:
                    await message.edit(embed=embed, view=view)
                continue
            except discord.NotFound:
                pass
        message = await channel.send(embed=embed, view=view)
        bot.store.set(f"{key}:{guild.id}", message.id)
    spam = guild.get_channel(SPAM_PROTECTION_CHANNEL_ID)
    if isinstance(spam, discord.TextChannel):
        await spam.set_permissions(guild.default_role, view_channel=True, send_messages=True, reason="Настройка антиспама")


def moderator_documentation_embeds() -> list[discord.Embed]:
    sections = (
        (
            "Заявки игроков",
            "В канале заявки используйте кнопки **Принять** и **Отклонить**. При принятии бот добавляет игрока в белый список, выдаёт роль игрока и устанавливает серверный ник из заявки. Отклонение требует указать причину.",
        ),
        (
            "Обращения и тикеты",
            "Хелперы и администраторы могут читать и вести открытые тикеты.\n`/добавить` — открыть выбранному игроку доступ к текущему тикету.\n**Закрыть обращение** — указать итоговое решение и удалить тикет.",
        ),
        (
            "Наказания",
            "`/бан ник причина` — бессрочный бан на Minecraft-сервере; перед выполнением требуется подтверждение.\n`/разбан ник причина` — снять бан.\n`/мут ник время причина` — выдать мут.\n`/размут ник причина` — снять мут.\n`/пред ник причина` — выдать предупреждение; перед третьим требуется подтверждение.\n`/разпред ник причина` — снять последнее активное предупреждение.\n`/наказания ник` — показать действия за последний месяц и актуальные наказания.",
        ),
        (
            "Формат указания времени",
            "Используйте число и букву без пробела: `30м`, `12ч`, `3д`. Предупреждение действует 3 дня. Третье активное предупреждение приводит к бессрочному бану на Minecraft-сервере.",
        ),
        (
            "Права модераторов",
            "Хелперы могут наказывать игроков, но не хелперов и администраторов. Администраторы могут наказывать хелперов. Ботов, владельца сервера и самого себя наказать нельзя.",
        ),
        (
            "Временные войсы и статистика",
            "После входа в канал создания войса игрок получает собственный канал и панель управления. Создатель войса может менять название, лимит, закрывать канал и управлять доступом. Голосовые каналы статистики показывают IP, число участников, игроков с ролью и онлайн Minecraft. Подключение к ним закрыто.",
        ),
        (
            "Ежедневная сводка",
            "Каждый день в 00:00 по московскому времени в канале логов публикуется сводка за прошедший день.",
        ),
    )
    return [
        discord.Embed(title=title, description=description, colour=colour(GOLD_EMBED_COLOR_HTML))
        for title, description in sections
    ]


async def update_moderator_documentation(guild: discord.Guild) -> None:
    channel = guild.get_channel(DOCUMENTATION_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        logging.warning("Канал документации %s не найден", DOCUMENTATION_CHANNEL_ID)
        return
    message_id = bot.store.get(f"documentation:{guild.id}") or DOCUMENTATION_MESSAGE_ID
    try:
        message = await channel.fetch_message(message_id)
        await message.edit(content=None, embeds=moderator_documentation_embeds(), view=None)
    except discord.NotFound:
        message = await channel.send(embeds=moderator_documentation_embeds())
    except discord.Forbidden:
        logging.warning("Не удалось изменить прежнее сообщение документации, создаётся новое")
        message = await channel.send(embeds=moderator_documentation_embeds())
    bot.store.set(f"documentation:{guild.id}", message.id)


async def daily_log_actions(guild: discord.Guild, summary_day: date) -> Counter[str]:
    channel = guild.get_channel(LOG_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        return Counter()
    start = datetime.combine(summary_day, time.min, tzinfo=MOSCOW_TIMEZONE).astimezone(timezone.utc)
    end = (datetime.combine(summary_day, time.min, tzinfo=MOSCOW_TIMEZONE) + timedelta(days=1)).astimezone(timezone.utc)
    actions: Counter[str] = Counter()
    async for message in channel.history(limit=None, after=start, before=end, oldest_first=True):
        for embed in message.embeds:
            if embed.title and embed.title.startswith("Лог • "):
                actions[embed.title.removeprefix("Лог • ")] += 1
    return actions


async def publish_daily_summary(guild: discord.Guild, summary_day: date) -> None:
    channel = guild.get_channel(LOG_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        logging.warning("Канал логов для ежедневной сводки не найден")
        return
    actions = await daily_log_actions(guild, summary_day)
    metrics = bot.store.daily_metrics(summary_day)
    accepted = actions["Заявка принята"]
    rejected = actions["Заявка отклонена"]
    event_accepted = actions["Ивент одобрен"]
    event_rejected = actions["Заявка на ивент отклонена"]
    tickets_closed = actions["Обращение закрыто модератором"] + actions["Проблема решена игроком"]
    punishment_lines = (
        f"Баны: **{actions['Пользователь заблокирован'] + actions['Пользователь автоматически заблокирован']}** · снято: **{actions['Пользователь разблокирован']}**\n"
        f"Муты: **{actions['Пользователю выдан мут']}** · снято: **{actions['С пользователя снят мут'] + actions['Мут автоматически снят']}**\n"
        f"Предупреждения: **{actions['Пользователю выдано предупреждение']}** · снято: **{actions['С пользователя снято предупреждение'] + actions['Предупреждение автоматически снято']}**"
    )
    embed = discord.Embed(
        title=f"Сводка за {summary_day.strftime('%d.%m.%Y')}",
        colour=colour(GOLD_EMBED_COLOR_HTML),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Участники", value=f"Новых: **{metrics.get('new_members', 0)}**\nПиковый онлайн Minecraft: **{metrics.get('peak_online', 0)}**", inline=False)
    embed.add_field(name="Заявки", value=f"Принято: **{accepted}** · отклонено: **{rejected}**\nИвенты: **{event_accepted}** одобрено · **{event_rejected}** отклонено", inline=False)
    embed.add_field(name="Тикеты", value=f"Закрыто: **{tickets_closed}**", inline=False)
    embed.add_field(name="Наказания", value=punishment_lines, inline=False)
    embed.add_field(name="Ошибки связи с Minecraft", value=f"**{metrics.get('rcon_errors', 0)}**", inline=False)
    new_message = await channel.send(embed=embed)

    previous_id = bot.store.get(f"daily_summary_message:{guild.id}")
    if previous_id and previous_id != new_message.id:
        try:
            await (await channel.fetch_message(previous_id)).delete()
        except (discord.NotFound, discord.Forbidden):
            pass
    bot.store.set(f"daily_summary_message:{guild.id}", new_message.id)
    bot.store.set(f"daily_summary_date:{guild.id}", int(summary_day.strftime("%Y%m%d")))


async def ensure_daily_summary(guild: discord.Guild) -> None:
    async with bot.daily_summary_lock:
        summary_day = datetime.now(MOSCOW_TIMEZONE).date() - timedelta(days=1)
        summary_key = int(summary_day.strftime("%Y%m%d"))
        if bot.store.get(f"daily_summary_date:{guild.id}") == summary_key:
            return
        await publish_daily_summary(guild, summary_day)


@tasks.loop(time=time(hour=0, minute=0, tzinfo=MOSCOW_TIMEZONE))
async def daily_summary_loop() -> None:
    for guild in bot.guilds:
        try:
            await ensure_daily_summary(guild)
        except Exception:
            logging.exception("Не удалось опубликовать ежедневную сводку сервера %s", guild.id)


@daily_summary_loop.before_loop
async def before_daily_summary_loop() -> None:
    await bot.wait_until_ready()


async def restore(guild: discord.Guild) -> None:
    for key, view in (("application", ApplicationPanel()), ("help", HelpPanel())):
        message_id = bot.store.get(f"{key}:{guild.id}")
        if message_id:
            bot.add_view(view, message_id=message_id)
    app_category = guild.get_channel(APPLICATION_CATEGORY_ID)
    if isinstance(app_category, discord.CategoryChannel):
        for channel in app_category.text_channels:
            user_id = owner(channel, APP_PREFIX)
            if user_id and "pending" in (channel.topic or ""):
                bot.add_view(ApplicationDecision(user_id))
            event_user_id = owner(channel, EVENT_PREFIX)
            if event_user_id and "pending" in (channel.topic or ""):
                bot.add_view(EventDecision(event_user_id))
    ticket_category = guild.get_channel(TICKET_CATEGORY_ID)
    if isinstance(ticket_category, discord.CategoryChannel):
        for channel in ticket_category.text_channels:
            event_user_id = owner(channel, EVENT_PREFIX)
            if event_user_id and "pending" in (channel.topic or ""):
                bot.add_view(EventDecision(event_user_id))
            user_id = owner(channel, TICKET_PREFIX)
            if user_id:
                ticket_owner = guild.get_member(user_id)
                if ticket_owner:
                    user_overwrite = channel.overwrites_for(ticket_owner)
                    if user_overwrite.attach_files is not True:
                        user_overwrite.attach_files = True
                        try:
                            await channel.set_permissions(
                                ticket_owner,
                                overwrite=user_overwrite,
                                reason="Разрешение прикреплять файлы автору обращения",
                            )
                        except discord.HTTPException:
                            logging.exception("Не удалось обновить права автора обращения %s", channel.id)
                try:
                    await restore_shared_ticket_permissions(channel)
                except discord.HTTPException:
                    logging.exception("Не удалось восстановить общие права модераторов в тикете %s", channel.id)
                controls = TicketControls(user_id)
                bot.add_view(controls)
                try:
                    async for message in channel.history(limit=1000, oldest_first=True):
                        if message.author == bot.user and any(embed.title == ticket_topic(channel) for embed in message.embeds):
                            await message.edit(view=TicketControls(user_id))
                            break
                except discord.HTTPException:
                    logging.exception("Не удалось убрать старые кнопки управления тикетом %s", channel.id)
    for voice_id, user_id, closed in bot.store.voices():
        voice = guild.get_channel(voice_id)
        if isinstance(voice, discord.VoiceChannel):
            try:
                await voice.set_permissions(
                    guild.default_role,
                    view_channel=True,
                    connect=not closed,
                    send_messages=True,
                    read_message_history=True,
                    reason="Доступ к чату временного войса для всех пользователей",
                )
            except discord.HTTPException:
                logging.exception("Не удалось обновить права чата временного войса %s", voice_id)
            bot.add_view(VoiceControls(voice_id, user_id, closed))
            try:
                async for message in voice.history(limit=20):
                    if message.author == bot.user and any(embed.title == "Управление войсом" for embed in message.embeds):
                        await message.edit(embed=voice_control_embed(), view=VoiceControls(voice_id, user_id, closed))
                        break
            except discord.HTTPException:
                logging.exception("Не удалось обновить панель управления войсом %s", voice_id)
        else:
            bot.store.remove_voice(voice_id)


# ============================================================
# ЗАЯВКИ
# ============================================================


class ApplicationForm(discord.ui.Modal, title="Заявка игрока"):
    nickname = discord.ui.TextInput(label="Никнейм", required=True, max_length=100)
    age = discord.ui.TextInput(label="Возраст", required=True, max_length=3)
    about = discord.ui.TextInput(label="Кратко о себе", required=True, style=discord.TextStyle.paragraph, max_length=1000)
    source = discord.ui.TextInput(label="Откуда узнали про нас?", required=False, max_length=300)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Заявку можно подать только на сервере", ephemeral=True)
            return
        roles = await bot.roles(interaction.guild)
        if interaction.user.get_role(PLAYER_ROLE_ID):
            await interaction.response.send_message("У вас уже есть роль игрока", ephemeral=True)
            return
        category = interaction.guild.get_channel(APPLICATION_CATEGORY_ID)
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message("Категория заявок не найдена", ephemeral=True)
            return
        if any(owner(channel, APP_PREFIX) == interaction.user.id and "pending" in (channel.topic or "") for channel in category.text_channels):
            await interaction.response.send_message("У вас уже есть активная заявка", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            roles[2]: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            roles[3]: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        if bot.user:
            overwrites[discord.Object(id=bot.user.id)] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_messages=True,
            )
        try:
            channel = await interaction.guild.create_text_channel(channel_name("заявка", interaction.user), category=category, overwrites=overwrites, topic=f"{APP_PREFIX}{interaction.user.id};pending", reason=f"Заявка от {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send("Боту не хватает прав для создания канала заявки в этой категории", ephemeral=True)
            return
        except discord.HTTPException:
            logging.exception("Не удалось создать канал заявки")
            await interaction.followup.send("Не удалось создать канал заявки. Попробуйте ещё раз позже", ephemeral=True)
            return
        embed = discord.Embed(title="Новая заявка", colour=colour(APPLICATION_EMBED_COLOR_HTML), timestamp=datetime.now(timezone.utc))
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        for label, value, inline in (
            ("Пользователь", interaction.user.mention, False),
            ("Никнейм", self.nickname.value, True),
            ("Возраст", self.age.value, True),
            ("Кратко о себе", self.about.value, False),
            ("Откуда узнали про нас?", self.source.value or "Не указано", False),
        ):
            embed.add_field(name=label, value=value, inline=inline)
        try:
            await channel.send(content=f"{interaction.user.mention} {roles[2].mention} {roles[3].mention}", embed=embed, view=ApplicationDecision(interaction.user.id), allowed_mentions=discord.AllowedMentions(users=True, roles=True))
        except discord.HTTPException:
            logging.exception("Не удалось отправить заявку в созданный канал")
            try:
                await channel.delete(reason="Не удалось отправить форму заявки")
            except discord.HTTPException:
                pass
            await interaction.followup.send("Не удалось отправить форму заявки. Попробуйте ещё раз позже", ephemeral=True)
            return
        bot.store.add_application(channel.id, self.nickname.value)
        await interaction.followup.send(f"Заявка отправлена: {channel.mention}. Ожидайте решение в личных сообщениях", ephemeral=True)


class GameRulesView(discord.ui.View):
    def __init__(self, user_id: int) -> None:
        super().__init__(timeout=120)
        self.user_id = user_id

    @discord.ui.button(label="Ознакомлен с правилами", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Эта кнопка доступна только автору заявки", ephemeral=True)
            return
        await show_modal(interaction, ApplicationForm())


class ApplicationPanel(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Подать заявку", style=discord.ButtonStyle.primary, custom_id="app:open:v2")
    async def open(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild and isinstance(interaction.user, discord.Member) and interaction.user.get_role(PLAYER_ROLE_ID):
            await interaction.response.send_message("У вас уже есть роль игрока", ephemeral=True)
            return
        embed = discord.Embed(title="Правила игры на сервере", description=f"После ознакомления с каналом <#{RULES_CHANNEL_ID}> нажмите кнопку ниже", colour=colour(APPLICATION_PANEL_COLOR_HTML))
        await interaction.response.send_message(embed=embed, view=GameRulesView(interaction.user.id), ephemeral=True)

# ============================================================
# ЗАЯВКИ НА ИВЕНТЫ
# ============================================================


def event_application_embed(member: discord.abc.User, name: str, event_time: str, description: str) -> discord.Embed:
    embed = discord.Embed(title="Заявка на проведение ивента", colour=colour(APPLICATION_EMBED_COLOR_HTML), timestamp=datetime.now(timezone.utc))
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Пользователь", value=member.mention, inline=False)
    embed.add_field(name="Название ивента", value=name, inline=False)
    embed.add_field(name="Дата и время по МСК", value=event_time, inline=False)
    embed.add_field(name="Описание", value=description, inline=False)
    return embed


class EventForm(discord.ui.Modal, title="Провести ивент"):
    event_name = discord.ui.TextInput(label="Название ивента", required=True, max_length=100)
    event_time = discord.ui.TextInput(label="Дата и время по МСК", required=True, max_length=100, placeholder="Например: 15 сентября, 19:00 МСК")
    description = discord.ui.TextInput(label="Описание ивента", required=True, style=discord.TextStyle.paragraph, max_length=1000)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Заявку на ивент можно подать только на сервере", ephemeral=True)
            return
        if not interaction.user.get_role(PLAYER_ROLE_ID):
            await interaction.response.send_message("Заявку на проведение ивента могут подать только игроки", ephemeral=True)
            return
        roles = await bot.roles(interaction.guild)
        mod_roles = await moderation_roles(interaction.guild)
        if mod_roles["mute"] in interaction.user.roles:
            await interaction.response.send_message("Во время мута нельзя подать заявку на проведение ивента", ephemeral=True)
            return
        category = interaction.guild.get_channel(TICKET_CATEGORY_ID)
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message("Категория помощи не найдена", ephemeral=True)
            return
        application_category = interaction.guild.get_channel(APPLICATION_CATEGORY_ID)
        event_categories = [category]
        if isinstance(application_category, discord.CategoryChannel):
            event_categories.append(application_category)
        if any(
            owner(channel, EVENT_PREFIX) == interaction.user.id and "pending" in (channel.topic or "")
            for event_category in event_categories
            for channel in event_category.text_channels
        ):
            await interaction.response.send_message("У вас уже есть активная заявка на проведение ивента", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            mod_roles["mute"]: discord.PermissionOverwrite(send_messages=False, send_messages_in_threads=False, add_reactions=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True),
            roles[2]: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True),
            roles[3]: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True),
        }
        if bot.user:
            overwrites[discord.Object(id=bot.user.id)] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                manage_channels=True,
                manage_messages=True,
            )
        try:
            channel = await interaction.guild.create_text_channel(
                channel_name(TICKET_CHANNEL_PREFIXES["event"], interaction.user),
                category=category,
                overwrites=overwrites,
                topic=f"{EVENT_PREFIX}{interaction.user.id};pending",
                reason=f"Заявка на ивент от {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.followup.send("Боту не хватает прав для создания канала заявки в этой категории", ephemeral=True)
            return
        except discord.HTTPException:
            logging.exception("Не удалось создать канал заявки на ивент")
            await interaction.followup.send("Не удалось создать канал заявки. Попробуйте ещё раз позже", ephemeral=True)
            return
        embed = event_application_embed(interaction.user, self.event_name.value, self.event_time.value, self.description.value)
        try:
            await channel.send(
                content=f"{interaction.user.mention} {roles[2].mention} {roles[3].mention}",
                embed=embed,
                view=EventDecision(interaction.user.id),
                allowed_mentions=discord.AllowedMentions(users=True, roles=True),
            )
        except discord.HTTPException:
            logging.exception("Не удалось отправить заявку на ивент в созданный канал")
            try:
                await channel.delete(reason="Не удалось отправить форму заявки на ивент")
            except discord.HTTPException:
                pass
            await interaction.followup.send("Не удалось отправить форму заявки на ивент. Попробуйте ещё раз позже", ephemeral=True)
            return
        await interaction.followup.send(
            f"Заявка на ивент отправлена: {channel.mention}. Чтобы прикрепить фотографии, отправьте изображения в канал с заявкой",
            ephemeral=True,
        )


class EventRejectionForm(discord.ui.Modal, title="Отклонение заявки на ивент"):
    reason = discord.ui.TextInput(label="Причина отказа", required=True, style=discord.TextStyle.paragraph, max_length=1000)

    def __init__(self, user_id: int, message_id: int) -> None:
        super().__init__()
        self.user_id = user_id
        self.message_id = message_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await staff(interaction) or not interaction.guild or not isinstance(interaction.user, discord.Member) or not isinstance(interaction.channel, discord.TextChannel):
            return
        await interaction.response.defer(ephemeral=True)
        applicant = interaction.guild.get_member(self.user_id)
        details = await event_details(interaction.channel)
        if applicant:
            await dm(
                applicant,
                discord.Embed(
                    title="Заявка на ивент отклонена",
                    description=f"Причина: {self.reason.value}\nОтклонил: {interaction.user.mention}",
                    colour=colour(APPLICATION_REJECTED_COLOR_HTML),
                ),
            )
        await interaction.channel.edit(topic=f"{EVENT_PREFIX}{self.user_id};rejected", reason=f"Заявка на ивент отклонена {interaction.user}")
        try:
            await (await interaction.channel.fetch_message(self.message_id)).edit(view=None)
        except discord.NotFound:
            pass
        log_fields: dict[str, object] = {
            "Модератор": interaction.user.mention,
            "Пользователь": details.get("Пользователь", f"<@{self.user_id}>"),
        }
        log_fields.update({name: value for name, value in details.items() if name != "Пользователь"})
        log_fields["Причина"] = self.reason.value
        await bot.log(
            interaction.guild,
            "Заявка на ивент отклонена",
            log_fields,
            avatar_url=str(applicant.display_avatar.url) if applicant else None,
            embed_color_html=APPLICATION_REJECTED_COLOR_HTML,
        )
        await interaction.followup.send("Заявка на ивент отклонена", ephemeral=True)
        await asyncio.sleep(2)
        await interaction.channel.delete(reason="Заявка на ивент отклонена")


class EventReworkForm(discord.ui.Modal, title="Доработка ивента"):
    event_name = discord.ui.TextInput(label="Название ивента", required=True, max_length=100)
    event_time = discord.ui.TextInput(label="Дата и время по МСК", required=True, max_length=100)
    description = discord.ui.TextInput(label="Описание ивента", required=True, style=discord.TextStyle.paragraph, max_length=1000)

    def __init__(self, user_id: int, message_id: int, details: dict[str, str]) -> None:
        super().__init__()
        self.user_id = user_id
        self.message_id = message_id
        self.event_name.default = details.get("Название ивента", "")
        self.event_time.default = details.get("Дата и время по МСК", details.get("Дата и время проведения", ""))
        self.description.default = details.get("Описание", "")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await staff(interaction) or not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            return
        applicant = interaction.guild.get_member(self.user_id)
        if applicant is None:
            await interaction.response.send_message("Пользователь больше не находится на сервере", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            message = await interaction.channel.fetch_message(self.message_id)
        except discord.NotFound:
            await interaction.followup.send("Сообщение с заявкой не найдено", ephemeral=True)
            return
        await message.edit(embed=event_application_embed(applicant, self.event_name.value, self.event_time.value, self.description.value))
        await interaction.followup.send("Данные заявки обновлены", ephemeral=True)


class EventDecision(discord.ui.View):
    def __init__(self, user_id: int) -> None:
        super().__init__(timeout=None)
        self.user_id = user_id
        self.accept.custom_id = f"event:accept:{user_id}"
        self.rework.custom_id = f"event:rework:{user_id}"
        self.reject.custom_id = f"event:reject:{user_id}"

    @discord.ui.button(label="Одобрить", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await staff(interaction) or not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            return
        await interaction.response.defer(ephemeral=True)
        details = await event_details(interaction.channel)
        name = details.get("Название ивента")
        event_time = details.get("Дата и время по МСК") or details.get("Дата и время проведения")
        description = details.get("Описание")
        if not name or not event_time or not description:
            await interaction.followup.send("Не удалось найти данные заявки на ивент", ephemeral=True)
            return
        events_channel = interaction.guild.get_channel(EVENTS_CHANNEL_ID)
        event_role = interaction.guild.get_role(EVENTS_ROLE_ID)
        if not isinstance(events_channel, discord.TextChannel) or event_role is None:
            await interaction.followup.send("Не найден канал или роль ивентов из настроек бота", ephemeral=True)
            return
        applicant = interaction.guild.get_member(self.user_id)
        organizer_name = applicant.display_name if applicant else str(self.user_id)
        title_embed = discord.Embed(title=name, colour=colour(APPLICATION_EMBED_COLOR_HTML))
        description_embed = discord.Embed(description=description, colour=colour(APPLICATION_EMBED_COLOR_HTML))
        description_embed.set_footer(text=f"{event_time} • {organizer_name}")
        try:
            await events_channel.send(content=event_role.mention, embed=title_embed, allowed_mentions=discord.AllowedMentions(roles=True))
        except discord.Forbidden:
            await interaction.followup.send("Боту не хватает прав для отправки сообщения в канал ивентов", ephemeral=True)
            return
        except discord.HTTPException:
            logging.exception("Не удалось опубликовать одобренный ивент")
            await interaction.followup.send("Не удалось опубликовать ивент. Попробуйте ещё раз", ephemeral=True)
            return
        skipped_photos = 0
        for attachment in await event_photos(interaction.channel, self.user_id):
            try:
                photo_file = await attachment.to_file()
                photo_embed = discord.Embed(colour=colour(APPLICATION_EMBED_COLOR_HTML))
                photo_embed.set_image(url=f"attachment://{photo_file.filename}")
                await events_channel.send(embed=photo_embed, file=photo_file)
            except discord.HTTPException:
                skipped_photos += 1
                logging.exception("Не удалось опубликовать фотографию ивента")
        try:
            await events_channel.send(embed=description_embed)
        except discord.Forbidden:
            await interaction.followup.send("Боту не хватает прав для отправки описания ивента", ephemeral=True)
            return
        except discord.HTTPException:
            logging.exception("Не удалось опубликовать описание ивента")
            await interaction.followup.send("Не удалось опубликовать описание ивента. Попробуйте ещё раз", ephemeral=True)
            return
        await interaction.channel.edit(topic=f"{EVENT_PREFIX}{self.user_id};accepted", reason=f"Ивент одобрен {interaction.user}")
        if interaction.message:
            await interaction.message.edit(view=None)
        await bot.log(
            interaction.guild,
            "Ивент одобрен",
            {
                "Модератор": interaction.user.mention,
                "Пользователь": applicant.mention if applicant else f"<@{self.user_id}>",
                "Название ивента": name,
                "Дата и время по МСК": event_time,
                "Описание": description,
            },
            avatar_url=str(applicant.display_avatar.url) if applicant else None,
            embed_color_html=APPLICATION_ACCEPTED_COLOR_HTML,
        )
        result = "Ивент одобрен и опубликован в канале ивентов"
        if skipped_photos:
            result += f". Не удалось отправить фотографий: {skipped_photos}"
        await interaction.followup.send(result, ephemeral=True)
        await asyncio.sleep(2)
        await interaction.channel.delete(reason="Ивент одобрен")

    @discord.ui.button(label="Доработать", style=discord.ButtonStyle.primary)
    async def rework(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await staff(interaction) or not isinstance(interaction.channel, discord.TextChannel) or not interaction.message:
            return
        details = embed_details(interaction.message, "Заявка на проведение ивента")
        await show_modal(interaction, EventReworkForm(self.user_id, interaction.message.id, details))

    @discord.ui.button(label="Отклонить", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if await staff(interaction) and interaction.message:
            await show_modal(interaction, EventRejectionForm(self.user_id, interaction.message.id))


class RejectionForm(discord.ui.Modal, title="Отклонение заявки"):
    reason = discord.ui.TextInput(label="Причина отказа", required=True, style=discord.TextStyle.paragraph, max_length=1000)

    def __init__(self, user_id: int, message_id: int) -> None:
        super().__init__()
        self.user_id = user_id
        self.message_id = message_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await staff(interaction) or not interaction.guild or not isinstance(interaction.user, discord.Member) or not isinstance(interaction.channel, discord.TextChannel):
            return
        await interaction.response.defer(ephemeral=True)
        applicant = interaction.guild.get_member(self.user_id)
        details = await application_details(interaction.channel)
        if applicant:
            await dm(applicant, discord.Embed(title="Заявка отклонена", description=f"Причина: {self.reason.value}\nОтклонил: {interaction.user.mention}", colour=colour(APPLICATION_REJECTED_COLOR_HTML)))
        avatar_owner = applicant
        if avatar_owner is None:
            try:
                avatar_owner = await bot.fetch_user(self.user_id)
            except discord.HTTPException:
                pass
        await interaction.channel.edit(topic=f"{APP_PREFIX}{self.user_id};rejected", reason=f"Заявка отклонена {interaction.user}")
        try:
            await (await interaction.channel.fetch_message(self.message_id)).edit(view=None)
        except discord.NotFound:
            pass
        log_fields: dict[str, object] = {
            "Модератор": interaction.user.mention,
            "Пользователь": details.get("Пользователь", f"<@{self.user_id}>"),
        }
        log_fields.update({name: value for name, value in details.items() if name != "Пользователь"})
        log_fields["Причина"] = self.reason.value
        await bot.log(
            interaction.guild,
            "Заявка отклонена",
            log_fields,
            avatar_url=str(avatar_owner.display_avatar.url) if avatar_owner else None,
            embed_color_html=APPLICATION_REJECTED_COLOR_HTML,
        )
        bot.store.remove_application(interaction.channel.id)
        await interaction.followup.send("Заявка отклонена", ephemeral=True)
        await asyncio.sleep(2)
        await interaction.channel.delete(reason="Заявка отклонена")


class ApplicationDecision(discord.ui.View):
    def __init__(self, user_id: int) -> None:
        super().__init__(timeout=None)
        self.user_id = user_id
        self.accept.custom_id = f"app:accept:{user_id}"
        self.reject.custom_id = f"app:reject:{user_id}"

    @discord.ui.button(label="Принять", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        roles = await staff(interaction)
        if not roles or not interaction.guild or not isinstance(interaction.user, discord.Member) or not isinstance(interaction.channel, discord.TextChannel):
            return
        applicant = interaction.guild.get_member(self.user_id)
        if not applicant:
            await interaction.response.send_message("Пользователь больше не находится на сервере", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        nickname = await application_nickname(interaction.channel)
        if not nickname:
            await interaction.followup.send("Не удалось найти никнейм из заявки", ephemeral=True)
            return
        linked_user_id = bot.store.player_for_nickname(interaction.guild.id, nickname)
        if linked_user_id is not None and linked_user_id != applicant.id:
            await interaction.followup.send(
                "Этот Minecraft-ник уже привязан к другому пользователю. Проверьте заявку перед одобрением",
                ephemeral=True,
            )
            return
        details = await application_details(interaction.channel)
        details["Пользователь"] = applicant.mention
        details.setdefault("Никнейм", nickname)
        try:
            await whitelist_player(nickname)
        except RconError as error:
            await interaction.followup.send(f"Не удалось добавить игрока в белый список: {error}", ephemeral=True)
            return
        try:
            await applicant.edit(nick=nickname, reason=f"Заявка одобрена {interaction.user}")
            await applicant.add_roles(roles[1], reason=f"Заявка одобрена {interaction.user}")
            await applicant.remove_roles(roles[0], reason=f"Заявка одобрена {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send(
                "Игрок добавлен в белый список, но бот не смог изменить его ник или роли. "
                "Проверьте право «Управлять никнеймами» и положение роли бота, затем нажмите «Принять» ещё раз",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            logging.exception("Не удалось изменить ник или роли пользователя %s при одобрении заявки", applicant.id)
            await interaction.followup.send(
                "Игрок добавлен в белый список, но Discord не принял изменение ника или ролей. Попробуйте ещё раз",
                ephemeral=True,
            )
            return
        try:
            bot.store.set_player_nickname(interaction.guild.id, applicant.id, nickname)
        except sqlite3.IntegrityError:
            logging.exception("Не удалось сохранить привязку Minecraft-ника %s", nickname)
            await interaction.followup.send(
                "Ник и роли изменены, но этот Minecraft-ник уже оказался привязан к другому пользователю. "
                "Заявка оставлена открытой для проверки",
                ephemeral=True,
            )
            return
        await dm(applicant, discord.Embed(title="Заявка принята", description=f"Заявку принял: {interaction.user.mention}\nДобро пожаловать на сервер! Приятной игры", colour=colour(APPLICATION_ACCEPTED_COLOR_HTML)))
        await interaction.channel.edit(topic=f"{APP_PREFIX}{self.user_id};accepted", reason=f"Заявка одобрена {interaction.user}")
        if interaction.message:
            await interaction.message.edit(view=None)
        await bot.log(
            interaction.guild,
            "Заявка принята",
            {"Модератор": interaction.user.mention, **details},
            avatar_url=str(applicant.display_avatar.url),
            embed_color_html=APPLICATION_ACCEPTED_COLOR_HTML,
        )
        bot.store.remove_application(interaction.channel.id)
        await interaction.followup.send("Заявка принята: игрок выдан, гость снят", ephemeral=True)
        await asyncio.sleep(2)
        await interaction.channel.delete(reason="Заявка принята")

    @discord.ui.button(label="Отклонить", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if await staff(interaction) and interaction.message:
            await show_modal(interaction, RejectionForm(self.user_id, interaction.message.id))


# ============================================================
# ОБРАЩЕНИЯ
# ============================================================


FORMS = {
    "bug": ("Баг-репорт", (("Ваш никнейм", True), ("Описание бага", True))),
    "login": ("Проблема со входом", (("Ваш никнейм", True), ("Что именно не работает?", True), ("Когда возникла проблема?", False))),
    "game": ("Проблема с игрой", (("Ваш никнейм", True), ("Версия игры", True), ("Опишите проблему", True), ("Как повторить проблему?", False))),
    "player": ("Жалоба на игрока", (("Ваш никнейм", True), ("Никнейм нарушителя", True), ("Что случилось?", True), ("Координаты", True), ("Нарушенный пункт правил", True))),
    "territory": ("Вопрос о территории", (("Ваш никнейм", True), ("Название территории или координаты", True), ("Ваш вопрос", True))),
    "donation": ("Проблема с донатом", (("Ваш никнейм", True), ("Что было приобретено?", True), ("Описание проблемы", True), ("Номер платежа (если есть)", False))),
    "admin": ("Жалоба на администратора", (("Ваш никнейм", True), ("Никнейм администратора", True), ("Что случилось?", True))),
    "appeal": ("Обжаловать наказание", (("Ваш никнейм", True), ("Какое наказание обжалуете?", True), ("Кто выдал наказание?", False), ("Почему наказание нужно пересмотреть?", True))),
    "other": ("Другое", (("Ваш никнейм", True), ("Опишите ситуацию", True))),
}


class HelpForm(discord.ui.Modal):
    def __init__(self, kind: str) -> None:
        title, fields = FORMS[kind]
        super().__init__(title=title[:45])
        self.kind = kind
        self.inputs: list[discord.ui.TextInput] = []
        long = {"Описание бага", "Что случилось?", "Что именно не работает?", "Ваш вопрос", "Описание проблемы", "Опишите проблему", "Как повторить проблему?", "Почему наказание нужно пересмотреть?", "Опишите ситуацию"}
        for label, required in fields:
            item = discord.ui.TextInput(label=label, required=required, style=discord.TextStyle.paragraph if label in long else discord.TextStyle.short, max_length=1000)
            self.inputs.append(item)
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Обращение можно создать только на сервере", ephemeral=True)
            return
        roles = await bot.roles(interaction.guild)
        mod_roles = await moderation_roles(interaction.guild)
        category = interaction.guild.get_channel(TICKET_CATEGORY_ID)
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message("Категория обращений не найдена", ephemeral=True)
            return
        open_tickets = [channel for channel in category.text_channels if owner(channel, TICKET_PREFIX) == interaction.user.id]
        has_appeal = any((channel.topic or "").partition(";")[2] == "appeal" for channel in open_tickets)
        if (self.kind == "appeal" and has_appeal) or (self.kind != "appeal" and open_tickets):
            await interaction.response.send_message("У вас уже есть открытое обращение", ephemeral=True)
            return
        if mod_roles["mute"] in interaction.user.roles and self.kind != "appeal":
            await interaction.response.send_message("Во время мута можно создать только обращение «Обжаловать наказание»", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            mod_roles["mute"]: discord.PermissionOverwrite(
                send_messages=False,
                send_messages_in_threads=False,
                add_reactions=False,
                speak=False,
            ),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            ),
            roles[2]: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True),
            roles[3]: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True),
        }
        channel = await interaction.guild.create_text_channel(
            channel_name(TICKET_CHANNEL_PREFIXES.get(self.kind, "обращение"), interaction.user),
            category=category,
            overwrites=overwrites,
            topic=f"{TICKET_PREFIX}{interaction.user.id};{self.kind}",
            reason=f"Обращение от {interaction.user}",
        )
        title, fields = FORMS[self.kind]
        embed = discord.Embed(title=title, colour=colour(TICKET_EMBED_COLOR_HTML), timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Автор", value=interaction.user.mention, inline=False)
        for (label, _), item in zip(fields, self.inputs):
            value = item.value or "Не указано"
            embed.add_field(name=label, value=value, inline=False)
        await channel.send(content=f"{interaction.user.mention} {roles[2].mention} {roles[3].mention}", embed=embed, view=TicketControls(interaction.user.id), allowed_mentions=discord.AllowedMentions(users=True, roles=True))
        await interaction.followup.send(f"Обращение создано: {channel.mention}", ephemeral=True)


class HelpSelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [discord.SelectOption(label=title, value=key) for key, (title, _) in FORMS.items()]
        options.append(discord.SelectOption(label="Провести ивент", value="event"))
        super().__init__(placeholder="Выберите тему обращения", custom_id="help:select", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.values[0] == "event":
            if not interaction.guild or not isinstance(interaction.user, discord.Member):
                await interaction.response.send_message("Заявку на ивент можно подать только на сервере", ephemeral=True)
                return
            if not interaction.user.get_role(PLAYER_ROLE_ID):
                await interaction.response.send_message("Заявку на проведение ивента могут подать только игроки", ephemeral=True)
                return
            await show_modal(interaction, EventForm())
            return
        await show_modal(interaction, HelpForm(self.values[0]))


class HelpMenu(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=120)
        self.add_item(HelpSelect())


class HelpPanel(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Обратиться за помощью", style=discord.ButtonStyle.primary, custom_id="help:open")
    async def open(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message("Выберите тему обращения:", view=HelpMenu(), ephemeral=True)


async def delete_ticket(channel: discord.TextChannel, action: str, fields: dict[str, object]) -> None:
    await bot.log(channel.guild, action, fields)
    await asyncio.sleep(2)
    try:
        await channel.delete(reason="Обращение закрыто")
    except discord.NotFound:
        pass


def is_ticket(channel: object) -> bool:
    return isinstance(channel, discord.TextChannel) and channel.category_id == TICKET_CATEGORY_ID and owner(channel, TICKET_PREFIX) is not None


def ticket_topic(channel: discord.TextChannel) -> str:
    kind = (channel.topic or "").partition(";")[2]
    return FORMS.get(kind, ("Не указано", ()))[0]


async def restore_shared_ticket_permissions(channel: discord.TextChannel) -> None:
    roles = await bot.roles(channel.guild)
    assignee_id = bot.store.ticket_assignee(channel.id)
    assignee = channel.guild.get_member(assignee_id) if assignee_id else None
    if assignee is not None and assignee.id != owner(channel, TICKET_PREFIX):
        await channel.set_permissions(
            assignee,
            overwrite=None,
            reason="Удаление персональных прав прежнего ответственного за тикет",
        )

    helper_overwrite = channel.overwrites_for(roles[2])
    helper_overwrite.view_channel = True
    helper_overwrite.read_message_history = True
    helper_overwrite.send_messages = True
    helper_overwrite.send_messages_in_threads = True
    helper_overwrite.attach_files = True
    helper_overwrite.add_reactions = True
    helper_overwrite.use_application_commands = True
    helper_overwrite.manage_messages = True
    await channel.set_permissions(
        roles[2],
        overwrite=helper_overwrite,
        reason="Общий доступ хелперов к тикету",
    )

    admin_overwrite = channel.overwrites_for(roles[3])
    admin_overwrite.view_channel = True
    admin_overwrite.read_message_history = True
    admin_overwrite.send_messages = True
    admin_overwrite.send_messages_in_threads = True
    admin_overwrite.attach_files = True
    admin_overwrite.add_reactions = True
    admin_overwrite.use_application_commands = True
    admin_overwrite.manage_messages = True
    await channel.set_permissions(
        roles[3],
        overwrite=admin_overwrite,
        reason="Постоянный доступ администраторов к тикету",
    )
    bot.store.remove_ticket_assignment(channel.id)


@bot.tree.command(name="добавить", description="Добавить пользователя в текущее обращение")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(user="Пользователь, которому нужно открыть доступ")
async def add_to_ticket(interaction: discord.Interaction, user: discord.Member) -> None:
    roles = await staff(interaction)
    if not roles or not interaction.guild or not is_ticket(interaction.channel):
        if roles:
            await interaction.response.send_message("Команду можно использовать только в канале обращения", ephemeral=True)
        return
    await interaction.response.defer()
    await interaction.channel.set_permissions(
        user,
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        attach_files=True,
        reason=f"Добавлен в обращение {interaction.user}",
    )
    await interaction.followup.send(
        f"Игрок {user.mention} добавлен в тикет",
        allowed_mentions=discord.AllowedMentions(users=True),
    )


class TicketCloseForm(discord.ui.Modal, title="Закрытие обращения"):
    solution = discord.ui.TextInput(label="Решение", required=True, style=discord.TextStyle.paragraph, max_length=1500)

    def __init__(self, user_id: int) -> None:
        super().__init__()
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await staff(interaction) or not isinstance(interaction.channel, discord.TextChannel) or not isinstance(interaction.user, discord.Member):
            return
        await interaction.response.send_message("Обращение будет удалено через несколько секунд", ephemeral=True)
        await delete_ticket(interaction.channel, "Обращение закрыто модератором", {
            "Модератор": interaction.user.mention,
            "Автор": f"<@{self.user_id}>",
            "Тема обращения": ticket_topic(interaction.channel),
            "Решение": self.solution.value,
        })


class TicketControls(discord.ui.View):
    def __init__(self, user_id: int) -> None:
        super().__init__(timeout=None)
        self.user_id = user_id
        self.resolved.custom_id = f"ticket:resolved:{user_id}"
        self.close.custom_id = f"ticket:close:{user_id}"

    @discord.ui.button(label="Проблема решена", style=discord.ButtonStyle.success)
    async def resolved(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Эта кнопка доступна только на сервере", ephemeral=True)
            return
        roles = await bot.roles(interaction.guild)
        if interaction.user.id != self.user_id or roles[1] not in interaction.user.roles:
            await interaction.response.send_message("Эту кнопку может нажать только игрок, создавший обращение", ephemeral=True)
            return
        await interaction.response.send_message("Спасибо! Обращение будет удалено через несколько секунд", ephemeral=True)
        await delete_ticket(interaction.channel, "Проблема решена игроком", {
            "Игрок": interaction.user.mention,
            "Тема обращения": ticket_topic(interaction.channel),
        })

    @discord.ui.button(label="Закрыть обращение", style=discord.ButtonStyle.primary)
    async def close(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if await staff(interaction):
            await show_modal(interaction, TicketCloseForm(self.user_id))


# ============================================================
# МОДЕРАЦИЯ
# ============================================================


def audit_reason(action: str, moderator: discord.abc.User | None, reason: str) -> str:
    moderator_name = str(moderator) if moderator else "Система"
    return f"{action} | {moderator_name} | {reason}"[:512]


def history_entry(row: sqlite3.Row, number: int) -> tuple[str, str]:
    labels = {
        "ban": "Бан",
        "unban": "Разбан",
        "mute": "Мут",
        "unmute": "Размут",
        "warn": "Предупреждение",
        "unwarn": "Снятие предупреждения",
    }
    kind = str(row["kind"])
    moderator = f"<@{row['moderator_id']}>" if row["moderator_id"] else "Система"
    reason = discord.utils.escape_markdown(capitalized_field_value(str(row["reason"])))[:500]
    title = f"{number}. {labels.get(kind, kind)} • <t:{row['created_at']}:f>"
    details = [f"**Причина:** {reason}", f"**Модератор:** {moderator}"]
    if row["expires_at"]:
        details.append(f"**Срок:**\n{punishment_period(int(row['created_at']), int(row['expires_at']))}")
    return title[:256], "\n".join(details)[:1024]


async def perform_ban(interaction: discord.Interaction, member: discord.Member, reason: str) -> None:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.followup.send("Команда доступна только на сервере", ephemeral=True)
        return
    nickname = await require_player_nickname(interaction, member)
    if nickname is None:
        return
    roles = await moderation_roles(interaction.guild)
    if bot.store.active_count(interaction.guild.id, member.id, "ban") or roles["ban"] in member.roles:
        await interaction.followup.send("У пользователя уже есть активный бан", ephemeral=True)
        return
    try:
        await member.add_roles(roles["ban"], reason=audit_reason("Бан", interaction.user, reason))
    except discord.Forbidden:
        await interaction.followup.send("Боту не хватает прав, чтобы выдать роль бана", ephemeral=True)
        return
    except discord.HTTPException:
        logging.exception("Не удалось выдать роль бана пользователю %s", member.id)
        await interaction.followup.send("Discord не принял роль бана. Попробуйте ещё раз", ephemeral=True)
        return
    try:
        await rcon_command(BAN_COMMAND.format(nickname=nickname, reason=safe_rcon_reason(reason)))
    except RconError as error:
        try:
            await member.remove_roles(roles["ban"], reason="Откат: Minecraft-бан не выполнен")
        except discord.HTTPException:
            logging.exception("Не удалось откатить роль бана пользователя %s", member.id)
        await interaction.followup.send(f"Не удалось заблокировать игрока в Minecraft: {error}", ephemeral=True)
        return
    bot.store.add_punishment(interaction.guild.id, member.id, "ban", interaction.user.id, reason, active=True)
    notice_sent = await dm(member, punishment_embed("Вы заблокированы на Minecraft-сервере", interaction.user, reason, appeal=True))
    await log_punishment(interaction.guild, "Пользователь заблокирован", member, interaction.user, reason, duration="Навсегда")
    suffix = "" if notice_sent else ". Личное сообщение доставить не удалось"
    await interaction.followup.send(f"{member.mention} заблокирован на Minecraft-сервере навсегда{suffix}", ephemeral=True)


class BanConfirmation(discord.ui.View):
    def __init__(self, moderator_id: int, member: discord.Member, reason: str) -> None:
        super().__init__(timeout=60)
        self.moderator_id = moderator_id
        self.member = member
        self.reason = reason

    @discord.ui.button(label="Подтвердить бан", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.moderator_id:
            await interaction.response.send_message("Подтвердить действие может только вызвавший команду модератор", ephemeral=True)
            return
        if not await moderation_target(interaction, self.member):
            return
        await interaction.response.edit_message(content="Блокировка выполняется…", embed=None, view=None)
        await perform_ban(interaction, self.member, self.reason)

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.moderator_id:
            await interaction.response.send_message("Отменить действие может только вызвавший команду модератор", ephemeral=True)
            return
        await interaction.response.edit_message(content="Блокировка отменена", embed=None, view=None)


@bot.tree.command(name="бан", description="Навсегда заблокировать игрока на Minecraft-сервере")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.rename(member="ник", reason="причина")
@app_commands.describe(member="Пользователь", reason="Причина блокировки")
async def ban_member(interaction: discord.Interaction, member: discord.Member, reason: app_commands.Range[str, 1, 1000]) -> None:
    if not await moderation_target(interaction, member) or not interaction.guild or not isinstance(interaction.user, discord.Member):
        return
    nickname = await require_player_nickname(interaction, member)
    if nickname is None:
        return
    roles = await moderation_roles(interaction.guild)
    if bot.store.active_count(interaction.guild.id, member.id, "ban") or roles["ban"] in member.roles:
        await interaction.response.send_message("У пользователя уже есть активный бан", ephemeral=True)
        return
    embed = discord.Embed(
        title="Подтверждение блокировки",
        description=(
            f"**Пользователь:** {member.mention} (`{nickname}`)\n"
            f"**Причина:** {capitalized_field_value(reason)}\n\n"
            "Блокировка на Minecraft-сервере будет бессрочной."
        ),
        colour=colour(APPLICATION_REJECTED_COLOR_HTML),
    )
    await interaction.response.send_message(
        embed=embed,
        view=BanConfirmation(interaction.user.id, member, reason),
        ephemeral=True,
    )


@bot.tree.command(name="разбан", description="Снять блокировку с пользователя")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.rename(member="ник", reason="причина")
@app_commands.describe(member="Пользователь", reason="Причина снятия блокировки")
async def unban_member(interaction: discord.Interaction, member: discord.Member, reason: app_commands.Range[str, 1, 1000]) -> None:
    if not await staff(interaction) or not interaction.guild or not isinstance(interaction.user, discord.Member):
        return
    nickname = await require_player_nickname(interaction, member)
    if nickname is None:
        return
    await interaction.response.defer(ephemeral=True)
    roles = await moderation_roles(interaction.guild)
    if not bot.store.active_count(interaction.guild.id, member.id, "ban") and roles["ban"] not in member.roles:
        await interaction.followup.send("У пользователя нет активного бана", ephemeral=True)
        return
    try:
        if roles["ban"] in member.roles:
            await member.remove_roles(roles["ban"], reason=audit_reason("Разбан", interaction.user, reason))
    except discord.Forbidden:
        await interaction.followup.send("Боту не хватает прав для снятия роли бана", ephemeral=True)
        return
    except discord.HTTPException:
        await interaction.followup.send("Discord не принял снятие роли бана. Попробуйте ещё раз", ephemeral=True)
        return
    try:
        await rcon_command(UNBAN_COMMAND.format(nickname=nickname))
    except RconError as error:
        try:
            await member.add_roles(roles["ban"], reason="Откат: Minecraft-разбан не выполнен")
        except discord.HTTPException:
            logging.exception("Не удалось вернуть роль бана пользователю %s", member.id)
        await interaction.followup.send(f"Не удалось снять бан в Minecraft: {error}", ephemeral=True)
        return
    bot.store.deactivate_all(interaction.guild.id, member.id, "ban")
    bot.store.add_punishment(interaction.guild.id, member.id, "unban", interaction.user.id, reason)
    await log_punishment(interaction.guild, "Пользователь разблокирован", member, interaction.user, reason, colour_html=APPLICATION_ACCEPTED_COLOR_HTML)
    await interaction.followup.send(f"Блокировка с {member.mention} снята", ephemeral=True)


@bot.tree.command(name="мут", description="Запретить пользователю писать и говорить")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.rename(member="ник", duration="время", reason="причина")
@app_commands.describe(member="Пользователь", duration="Например: 30м, 12ч или 3д", reason="Причина мута")
async def mute_member(
    interaction: discord.Interaction,
    member: discord.Member,
    duration: app_commands.Range[str, 2, 16],
    reason: app_commands.Range[str, 1, 1000],
) -> None:
    if not await moderation_target(interaction, member) or not interaction.guild or not isinstance(interaction.user, discord.Member):
        return
    nickname = await require_player_nickname(interaction, member)
    if nickname is None:
        return
    parsed = parse_duration(duration)
    if parsed is None:
        await interaction.response.send_message("Укажите время в формате `30м`, `12ч` или `3д` (не более 10 лет)", ephemeral=True)
        return
    seconds, _, rcon_duration = parsed
    await interaction.response.defer(ephemeral=True)
    roles = await moderation_roles(interaction.guild)
    started_at = int(datetime.now(timezone.utc).timestamp())
    expires_at = started_at + seconds
    duration_period = punishment_period(started_at, expires_at)
    async with bot.moderation_lock:
        if roles["mute"] in member.roles or bot.store.active_count(interaction.guild.id, member.id, "mute"):
            await interaction.followup.send("У пользователя уже есть активный мут", ephemeral=True)
            return
        try:
            await member.add_roles(roles["mute"], reason=audit_reason("Мут", interaction.user, reason))
        except discord.Forbidden:
            await interaction.followup.send("Боту не хватает прав, чтобы выдать роль мута", ephemeral=True)
            return
        except discord.HTTPException:
            logging.exception("Не удалось выдать роль мута пользователю %s", member.id)
            await interaction.followup.send("Discord не принял выдачу роли мута. Попробуйте ещё раз", ephemeral=True)
            return
        permission_failures = await apply_member_mute_overwrites(member)
        try:
            await rcon_command(TEMPMUTE_COMMAND.format(
                nickname=nickname,
                duration=rcon_duration,
                reason=safe_rcon_reason(reason),
            ))
        except RconError as error:
            await restore_member_mute_overwrites(member)
            try:
                await member.remove_roles(roles["mute"], reason="Откат: Minecraft-мут не выполнен")
            except discord.HTTPException:
                logging.exception("Не удалось откатить роль мута пользователя %s", member.id)
            await interaction.followup.send(f"Не удалось выдать мут в Minecraft: {error}", ephemeral=True)
            return
        bot.store.add_punishment(
            interaction.guild.id,
            member.id,
            "mute",
            interaction.user.id,
            reason,
            expires_at=expires_at,
            active=True,
            created_at=started_at,
        )
    notice_sent = await dm(
        member,
        punishment_embed("Вам выдан мут", interaction.user, reason, duration=duration_period),
    )
    await log_punishment(interaction.guild, "Пользователю выдан мут", member, interaction.user, reason, duration=duration_period)
    suffix = "" if notice_sent else ". Личное сообщение доставить не удалось"
    if permission_failures:
        suffix += f". Не удалось обновить права в каналах: {permission_failures}"
    await interaction.followup.send(f"{member.mention} получил мут до <t:{expires_at}:f>{suffix}", ephemeral=True)


@bot.tree.command(name="размут", description="Снять мут с пользователя")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.rename(member="ник", reason="причина")
@app_commands.describe(member="Пользователь", reason="Причина снятия мута")
async def unmute_member(interaction: discord.Interaction, member: discord.Member, reason: app_commands.Range[str, 1, 1000]) -> None:
    if not await staff(interaction) or not interaction.guild or not isinstance(interaction.user, discord.Member):
        return
    nickname = await require_player_nickname(interaction, member)
    if nickname is None:
        return
    await interaction.response.defer(ephemeral=True)
    roles = await moderation_roles(interaction.guild)
    async with bot.moderation_lock:
        active = bot.store.active_punishments(interaction.guild.id, member.id, "mute")
        if not active and roles["mute"] not in member.roles:
            await interaction.followup.send("У пользователя нет активного мута", ephemeral=True)
            return
        permission_failures = await restore_member_mute_overwrites(member)
        if permission_failures:
            await apply_member_mute_overwrites(member)
            await interaction.followup.send(
                f"Не удалось восстановить права пользователя в каналах: {permission_failures}. Попробуйте ещё раз",
                ephemeral=True,
            )
            return
        try:
            if roles["mute"] in member.roles:
                await member.remove_roles(roles["mute"], reason=audit_reason("Размут", interaction.user, reason))
        except discord.Forbidden:
            await apply_member_mute_overwrites(member)
            await interaction.followup.send("Боту не хватает прав, чтобы снять роль мута", ephemeral=True)
            return
        except discord.HTTPException:
            logging.exception("Не удалось снять роль мута с пользователя %s", member.id)
            await apply_member_mute_overwrites(member)
            await interaction.followup.send("Discord не принял снятие роли мута. Попробуйте ещё раз", ephemeral=True)
            return
        try:
            await rcon_command(UNMUTE_COMMAND.format(nickname=nickname))
        except RconError as error:
            try:
                await member.add_roles(roles["mute"], reason="Откат: Minecraft-размут не выполнен")
                await apply_member_mute_overwrites(member)
            except discord.HTTPException:
                logging.exception("Не удалось вернуть Discord-мут пользователю %s", member.id)
            await interaction.followup.send(f"Не удалось снять мут в Minecraft: {error}", ephemeral=True)
            return
        bot.store.deactivate_all(interaction.guild.id, member.id, "mute")
        bot.store.add_punishment(interaction.guild.id, member.id, "unmute", interaction.user.id, reason)
    await log_punishment(interaction.guild, "С пользователя снят мут", member, interaction.user, reason, colour_html=APPLICATION_ACCEPTED_COLOR_HTML)
    await interaction.followup.send(f"Мут с {member.mention} снят", ephemeral=True)


async def perform_warning(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str,
    *,
    third_warning_confirmed: bool,
) -> None:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.followup.send("Команда доступна только на сервере", ephemeral=True)
        return
    nickname = await require_player_nickname(interaction, member)
    if nickname is None:
        return
    roles = await moderation_roles(interaction.guild)
    now = int(datetime.now(timezone.utc).timestamp())
    expires_at = now + WARNING_LIFETIME_SECONDS
    warning_period = punishment_period(now, expires_at)
    automatic_ban_key = (interaction.guild.id, member.id)
    async with bot.moderation_lock:
        if bot.store.active_count(interaction.guild.id, member.id, "warn") >= 2 and not third_warning_confirmed:
            await interaction.followup.send(
                "За время подтверждения число предупреждений изменилось. Повторите `/пред`, чтобы подтвердить третье предупреждение",
                ephemeral=True,
            )
            return
        if automatic_ban_key in bot.automatic_bans:
            await interaction.followup.send("Для пользователя уже выполняется автоматический бан", ephemeral=True)
            return
        if bot.store.active_count(interaction.guild.id, member.id, "ban") or roles["ban"] in member.roles:
            await interaction.followup.send("Пользователь уже заблокирован", ephemeral=True)
            return
        try:
            await rcon_command(WARN_COMMAND.format(nickname=nickname, reason=safe_rcon_reason(reason)))
        except RconError as error:
            await interaction.followup.send(f"Не удалось выдать предупреждение в Minecraft: {error}", ephemeral=True)
            return
        punishment_id = bot.store.add_punishment(
            interaction.guild.id,
            member.id,
            "warn",
            interaction.user.id,
            reason,
            expires_at=expires_at,
            active=True,
            created_at=now,
        )
        try:
            warning_count = await sync_warning_roles(member, roles)
        except discord.HTTPException:
            bot.store.deactivate(punishment_id)
            try:
                await rcon_command(UNWARN_COMMAND.format(nickname=nickname))
            except RconError:
                logging.exception("Не удалось откатить Minecraft-предупреждение пользователя %s", member.id)
                bot.store.activate(punishment_id)
                await interaction.followup.send(
                    "Предупреждение выдано в Minecraft, но боту не хватило прав для роли предупреждения",
                    ephemeral=True,
                )
                return
            await interaction.followup.send("Боту не хватает прав для роли предупреждения; выдача отменена", ephemeral=True)
            return
        if warning_count >= 3:
            bot.automatic_bans.add(automatic_ban_key)
    notice_sent = await dm(
        member,
        punishment_embed(
            "Вам выдано предупреждение",
            interaction.user,
            reason,
            duration=warning_period,
            extra=f"**Активных предупреждений:** {warning_count}/3",
        ),
    )
    await log_punishment(
        interaction.guild,
        "Пользователю выдано предупреждение",
        member,
        interaction.user,
        reason,
        duration=warning_period,
        colour_html=GOLD_EMBED_COLOR_HTML,
        extra_fields={"Предупреждений": f"{warning_count}/3"},
    )
    if warning_count < 3:
        suffix = "" if notice_sent else ". Личное сообщение доставить не удалось"
        await interaction.followup.send(f"{member.mention} получил предупреждение ({warning_count}/3){suffix}", ephemeral=True)
        return

    automatic_reason = "Получено третье предупреждение"
    try:
        await rcon_command(BAN_COMMAND.format(nickname=nickname, reason=automatic_reason))
    except RconError as error:
        async with bot.moderation_lock:
            bot.automatic_bans.discard(automatic_ban_key)
        await interaction.followup.send(
            f"Предупреждение выдано, но не удалось автоматически заблокировать игрока в Minecraft: {error}",
            ephemeral=True,
        )
        return
    bot.store.add_punishment(interaction.guild.id, member.id, "ban", None, automatic_reason, active=True, created_at=now)
    role_error: str | None = None
    try:
        await member.add_roles(roles["ban"], reason=audit_reason("Автоматический бан", None, automatic_reason))
    except discord.Forbidden:
        role_error = "Боту не хватило прав для выдачи роли бана"
    except discord.HTTPException:
        logging.exception("Не удалось автоматически выдать роль бана пользователю %s", member.id)
        role_error = "Discord не принял роль бана"
    finally:
        async with bot.moderation_lock:
            bot.automatic_bans.discard(automatic_ban_key)
    await dm(member, punishment_embed("Вы заблокированы на Minecraft-сервере", None, automatic_reason, appeal=True))
    await log_punishment(
        interaction.guild,
        "Пользователь автоматически заблокирован",
        member,
        None,
        automatic_reason,
        duration="Навсегда",
    )
    suffix = "" if notice_sent else ". Личное сообщение о предупреждении доставить не удалось"
    if role_error:
        suffix += f". Minecraft-бан выдан, но роль не назначена: {role_error}"
    await interaction.followup.send(
        f"{member.mention} получил третье предупреждение и навсегда заблокирован на Minecraft-сервере{suffix}",
        ephemeral=True,
    )


class ThirdWarningConfirmation(discord.ui.View):
    def __init__(self, moderator_id: int, member: discord.Member, reason: str) -> None:
        super().__init__(timeout=60)
        self.moderator_id = moderator_id
        self.member = member
        self.reason = reason

    @discord.ui.button(label="Выдать третье предупреждение", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.moderator_id:
            await interaction.response.send_message("Подтвердить действие может только вызвавший команду модератор", ephemeral=True)
            return
        if not await moderation_target(interaction, self.member):
            return
        await interaction.response.edit_message(content="Предупреждение выдаётся…", embed=None, view=None)
        await perform_warning(interaction, self.member, self.reason, third_warning_confirmed=True)

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.moderator_id:
            await interaction.response.send_message("Отменить действие может только вызвавший команду модератор", ephemeral=True)
            return
        await interaction.response.edit_message(content="Выдача предупреждения отменена", embed=None, view=None)


@bot.tree.command(name="пред", description="Выдать пользователю предупреждение")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.rename(member="ник", reason="причина")
@app_commands.describe(member="Пользователь", reason="Причина предупреждения")
async def warn_member(interaction: discord.Interaction, member: discord.Member, reason: app_commands.Range[str, 1, 1000]) -> None:
    if not await moderation_target(interaction, member) or not interaction.guild or not isinstance(interaction.user, discord.Member):
        return
    nickname = await require_player_nickname(interaction, member)
    if nickname is None:
        return
    warning_count = bot.store.active_count(interaction.guild.id, member.id, "warn")
    if warning_count >= 2:
        embed = discord.Embed(
            title="Подтверждение третьего предупреждения",
            description=(
                f"**Пользователь:** {member.mention} (`{nickname}`)\n"
                f"**Причина:** {capitalized_field_value(reason)}\n\n"
                "После выдачи предупреждения игрок будет бессрочно заблокирован на Minecraft-сервере."
            ),
            colour=colour(APPLICATION_REJECTED_COLOR_HTML),
        )
        await interaction.response.send_message(
            embed=embed,
            view=ThirdWarningConfirmation(interaction.user.id, member, reason),
            ephemeral=True,
        )
        return
    await interaction.response.defer(ephemeral=True)
    await perform_warning(interaction, member, reason, third_warning_confirmed=False)


@bot.tree.command(name="разпред", description="Снять последнее активное предупреждение")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.rename(member="ник", reason="причина")
@app_commands.describe(member="Пользователь", reason="Причина снятия предупреждения")
async def unwarn_member(interaction: discord.Interaction, member: discord.Member, reason: app_commands.Range[str, 1, 1000]) -> None:
    if not await staff(interaction) or not interaction.guild or not isinstance(interaction.user, discord.Member):
        return
    nickname = await require_player_nickname(interaction, member)
    if nickname is None:
        return
    await interaction.response.defer(ephemeral=True)
    roles = await moderation_roles(interaction.guild)
    async with bot.moderation_lock:
        if not bot.store.active_count(interaction.guild.id, member.id, "warn"):
            await interaction.followup.send("У пользователя нет активных предупреждений", ephemeral=True)
            return
        try:
            await rcon_command(UNWARN_COMMAND.format(nickname=nickname))
        except RconError as error:
            await interaction.followup.send(f"Не удалось снять предупреждение в Minecraft: {error}", ephemeral=True)
            return
        removed = bot.store.deactivate_latest_warning(interaction.guild.id, member.id)
        if removed is None:
            await interaction.followup.send("У пользователя нет активных предупреждений", ephemeral=True)
            return
        try:
            warning_count = await sync_warning_roles(member, roles)
        except discord.HTTPException:
            logging.exception("Не удалось обновить роль предупреждения пользователя %s", member.id)
            warning_count = bot.store.active_count(interaction.guild.id, member.id, "warn")
        bot.store.add_punishment(interaction.guild.id, member.id, "unwarn", interaction.user.id, reason)
    await log_punishment(interaction.guild, "С пользователя снято предупреждение", member, interaction.user, reason, colour_html=APPLICATION_ACCEPTED_COLOR_HTML)
    await interaction.followup.send(f"Предупреждение снято. Активных предупреждений: {warning_count}/3", ephemeral=True)


@bot.tree.command(name="наказания", description="Показать историю наказаний пользователя за последний месяц")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.rename(user="ник")
@app_commands.describe(user="Пользователь")
async def punishment_history(interaction: discord.Interaction, user: discord.User) -> None:
    if not await staff(interaction) or not interaction.guild:
        return
    await interaction.response.defer(ephemeral=True)
    now = int(datetime.now(timezone.utc).timestamp())
    active_bans = bot.store.active_punishments(interaction.guild.id, user.id, "ban")
    active_mutes = bot.store.active_punishments(interaction.guild.id, user.id, "mute")
    warning_count = bot.store.active_count(interaction.guild.id, user.id, "warn")
    current: list[str] = []
    if active_bans:
        active_ban = active_bans[-1]
        expiry = active_ban["expires_at"]
        current.append(
            f"Бан\n{punishment_period(int(active_ban['created_at']), int(expiry))}"
            if expiry else "Перманентный бан"
        )
    if active_mutes:
        active_mute = active_mutes[-1]
        expiry = active_mute["expires_at"]
        current.append(
            f"Мут\n{punishment_period(int(active_mute['created_at']), int(expiry))}"
            if expiry else "Мут"
        )
    if warning_count:
        current.append(f"Предупреждений: {warning_count}/3")
    rows = bot.store.punishment_history(interaction.guild.id, user.id, now - PUNISHMENT_HISTORY_SECONDS)
    current_text = "\n".join(f"• {item}" for item in current) if current else "Нет"
    rows_per_page = 7
    displayed_rows = rows[:rows_per_page * 10]
    row_pages = [displayed_rows[index:index + rows_per_page] for index in range(0, len(displayed_rows), rows_per_page)] or [[]]
    embeds: list[discord.Embed] = []
    for page_index, page_rows in enumerate(row_pages):
        embed = discord.Embed(
            title=f"История наказаний • {user.display_name}" if page_index == 0 else "История наказаний • продолжение",
            colour=colour(LOG_EMBED_COLOR_HTML),
            timestamp=datetime.now(timezone.utc) if page_index == 0 else None,
        )
        if page_index == 0:
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.add_field(name="Актуальные наказания", value=current_text, inline=False)
        if page_rows:
            for offset, row in enumerate(page_rows, start=page_index * rows_per_page + 1):
                name, value = history_entry(row, offset)
                embed.add_field(name=name, value=value, inline=False)
        elif page_index == 0:
            embed.add_field(name="История за последние 30 дней", value="Наказаний не найдено", inline=False)
        footer = f"Страница {page_index + 1}/{len(row_pages)}"
        if len(rows) > len(displayed_rows) and page_index == len(row_pages) - 1:
            footer += f" · показано {len(displayed_rows)} из {len(rows)}"
        embed.set_footer(text=footer)
        embeds.append(embed)
    await interaction.followup.send(embeds=embeds, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


async def process_expired_punishments(guild: discord.Guild, roles: dict[str, discord.Role] | None = None) -> None:
    roles = roles or await moderation_roles(guild)
    now = int(datetime.now(timezone.utc).timestamp())
    for row in bot.store.expired_punishments(guild.id, now):
        kind = str(row["kind"])
        member = guild.get_member(int(row["user_id"]))
        user: discord.abc.User | None = member
        if user is None:
            try:
                user = await bot.fetch_user(int(row["user_id"]))
            except discord.HTTPException:
                pass
        nickname = server_minecraft_nickname(member) if member is not None else None

        if kind == "ban":
            if nickname is None:
                logging.error("Не найден Minecraft-ник для автоматического разбана пользователя %s", row["user_id"])
                continue
            try:
                await rcon_command(UNBAN_COMMAND.format(nickname=nickname))
                if member is not None and roles["ban"] in member.roles:
                    await member.remove_roles(roles["ban"], reason=audit_reason("Автоматический разбан", None, "Истёк срок наказания"))
            except (RconError, discord.HTTPException):
                logging.exception("Не удалось автоматически снять Minecraft-бан с пользователя %s", row["user_id"])
                continue
            bot.store.deactivate(int(row["id"]))
            bot.store.add_punishment(guild.id, int(row["user_id"]), "unban", None, "Истёк срок наказания", created_at=now)
            if user:
                await log_punishment(guild, "Блокировка автоматически снята", user, None, "Истёк срок наказания", colour_html=APPLICATION_ACCEPTED_COLOR_HTML)
            continue

        if kind == "mute":
            if nickname is None:
                logging.error("Не найден Minecraft-ник для автоматического размута пользователя %s", row["user_id"])
                continue
            try:
                await rcon_command(UNMUTE_COMMAND.format(nickname=nickname))
            except RconError:
                logging.exception("Не удалось автоматически снять Minecraft-мут с пользователя %s", row["user_id"])
                continue
            if member is not None:
                permission_failures = await restore_member_mute_overwrites(member)
                if permission_failures:
                    await apply_member_mute_overwrites(member)
                    continue
                try:
                    if roles["mute"] in member.roles:
                        await member.remove_roles(roles["mute"], reason=audit_reason("Автоматический размут", None, "Истёк срок наказания"))
                except discord.HTTPException:
                    await apply_member_mute_overwrites(member)
                    logging.exception("Не удалось автоматически снять мут с пользователя %s", row["user_id"])
                    continue
            bot.store.deactivate(int(row["id"]))
            bot.store.add_punishment(guild.id, int(row["user_id"]), "unmute", None, "Истёк срок наказания", created_at=now)
            if user:
                await log_punishment(guild, "Мут автоматически снят", user, None, "Истёк срок наказания", colour_html=APPLICATION_ACCEPTED_COLOR_HTML)
            continue

        if kind == "warn":
            if nickname is None:
                logging.error("Не найден Minecraft-ник для автоматического снятия предупреждения пользователя %s", row["user_id"])
                continue
            try:
                await rcon_command(UNWARN_COMMAND.format(nickname=nickname))
            except RconError:
                logging.exception("Не удалось автоматически снять Minecraft-предупреждение пользователя %s", row["user_id"])
                continue
            bot.store.deactivate(int(row["id"]))
            if member is not None:
                try:
                    await sync_warning_roles(member, roles)
                except discord.HTTPException:
                    logging.exception("Не удалось обновить роль предупреждений пользователя %s", row["user_id"])
            bot.store.add_punishment(guild.id, int(row["user_id"]), "unwarn", None, "Истёк срок давности", created_at=now)
            if user:
                await log_punishment(guild, "Предупреждение автоматически снято", user, None, "Истёк срок давности", colour_html=APPLICATION_ACCEPTED_COLOR_HTML)
    bot.store.purge_old_punishments(now - PUNISHMENT_HISTORY_SECONDS)


@tasks.loop(minutes=1)
async def punishment_expiry_loop() -> None:
    for guild in bot.guilds:
        async with bot.moderation_lock:
            try:
                await process_expired_punishments(guild)
            except Exception:
                logging.exception("Не удалось проверить сроки наказаний на сервере %s", guild.id)


@punishment_expiry_loop.before_loop
async def before_punishment_expiry_loop() -> None:
    await bot.wait_until_ready()


# ============================================================
# ВОЙСЫ
# ============================================================


class SlotsForm(discord.ui.Modal, title="Количество мест"):
    slots = discord.ui.TextInput(label="Сколько мест будет в войсе?", required=True, max_length=2, placeholder="1–99")

    def __init__(self, voice_id: int, user_id: int, closed: bool, control_message: discord.Message) -> None:
        super().__init__()
        self.voice_id = voice_id
        self.user_id = user_id
        self.closed = closed
        self.control_message = control_message

    async def on_submit(self, interaction: discord.Interaction) -> None:
        voice, roles = await voice_access(interaction, self.voice_id, self.user_id)
        if not voice or not roles:
            return
        try:
            value = int(self.slots.value)
            if not 1 <= value <= 99:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Введите целое число от 1 до 99", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await voice.edit(user_limit=value, reason=f"Лимит изменён {interaction.user}")
        try:
            await self.control_message.edit(view=VoiceControls(self.voice_id, self.user_id, self.closed))
        except discord.HTTPException:
            logging.exception("Не удалось обновить панель управления войсом %s", self.voice_id)
        await interaction.followup.send(f"Лимит участников изменён: {value}", ephemeral=True)


class RenameVoiceForm(discord.ui.Modal, title="Переименовать войс"):
    name = discord.ui.TextInput(label="Новое название", required=True, max_length=100, placeholder="Например: Войс для игры")

    def __init__(self, voice_id: int, user_id: int, closed: bool, control_message: discord.Message) -> None:
        super().__init__()
        self.voice_id = voice_id
        self.user_id = user_id
        self.closed = closed
        self.control_message = control_message

    async def on_submit(self, interaction: discord.Interaction) -> None:
        voice, _ = await voice_access(interaction, self.voice_id, self.user_id)
        if not voice:
            return
        new_name = self.name.value.strip()
        if not new_name:
            await interaction.response.send_message("Название не может быть пустым", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await voice.edit(name=new_name, reason=f"Войс переименован {interaction.user}")
        try:
            await self.control_message.edit(view=VoiceControls(self.voice_id, self.user_id, self.closed))
        except discord.HTTPException:
            logging.exception("Не удалось обновить панель управления войсом %s", self.voice_id)
        await interaction.followup.send(f"Войс переименован: **{discord.utils.escape_markdown(new_name)}**", ephemeral=True)


async def voice_access(interaction: discord.Interaction, voice_id: int, user_id: int) -> tuple[discord.VoiceChannel | None, tuple[discord.Role, discord.Role, discord.Role, discord.Role] | None]:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Это действие доступно только на сервере", ephemeral=True)
        return None, None
    voice = interaction.guild.get_channel(voice_id)
    roles = await bot.roles(interaction.guild)
    if not isinstance(voice, discord.VoiceChannel):
        await interaction.response.send_message("Этот войс уже удалён", ephemeral=True)
        return None, None
    if interaction.user.id != user_id and not (interaction.user.guild_permissions.administrator or roles[2] in interaction.user.roles or roles[3] in interaction.user.roles):
        await interaction.response.send_message("Управлять войсом может его создатель, хелпер или администратор", ephemeral=True)
        return None, None
    return voice, roles


class KickMemberSelect(discord.ui.UserSelect):
    def __init__(self, voice_id: int, owner_id: int) -> None:
        super().__init__(placeholder="Выберите участника для исключения", min_values=1, max_values=1)
        self.voice_id = voice_id
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction) -> None:
        voice, _ = await voice_access(interaction, self.voice_id, self.owner_id)
        if not voice:
            return
        selected = self.values[0]
        member = selected if isinstance(selected, discord.Member) else interaction.guild.get_member(selected.id) if interaction.guild else None
        if not isinstance(member, discord.Member) or member.voice is None or member.voice.channel != voice:
            await interaction.response.send_message("Этот участник уже не находится в войсе", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            await member.move_to(None, reason=f"Исключён из временного войса пользователем {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send("Боту не хватает права перемещать участников", ephemeral=True)
            return
        except discord.HTTPException:
            await interaction.followup.send("Не удалось исключить участника. Попробуйте ещё раз", ephemeral=True)
            return
        await interaction.edit_original_response(content=f"{member.mention} исключён из войса", view=None)


class KickMemberView(discord.ui.View):
    def __init__(self, voice_id: int, owner_id: int) -> None:
        super().__init__(timeout=180)
        self.add_item(KickMemberSelect(voice_id, owner_id))


class VoiceControls(discord.ui.View):
    def __init__(self, voice_id: int, user_id: int, closed: bool) -> None:
        super().__init__(timeout=None)
        self.voice_id = voice_id
        self.user_id = user_id
        self.closed = closed
        self.slots.custom_id = f"voice:slots:{voice_id}:{user_id}"
        self.rename.custom_id = f"voice:rename:{voice_id}:{user_id}"
        self.kick.custom_id = f"voice:kick:{voice_id}:{user_id}"
        self.lock.custom_id = f"voice:lock:{voice_id}:{user_id}"
        self.lock.label = "Войс закрыт" if closed else "Войс открыт"
        self.lock.style = discord.ButtonStyle.danger if closed else discord.ButtonStyle.success

    @discord.ui.button(label="Кол-во мест", style=discord.ButtonStyle.primary)
    async def slots(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        voice, roles = await voice_access(interaction, self.voice_id, self.user_id)
        if voice and roles:
            await show_modal(interaction, SlotsForm(self.voice_id, self.user_id, self.closed, interaction.message))

    @discord.ui.button(label="Переименовать", style=discord.ButtonStyle.primary)
    async def rename(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        voice, roles = await voice_access(interaction, self.voice_id, self.user_id)
        if voice and roles:
            await show_modal(interaction, RenameVoiceForm(self.voice_id, self.user_id, self.closed, interaction.message))

    @discord.ui.button(label="Выгнать участника", style=discord.ButtonStyle.danger)
    async def kick(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        voice, roles = await voice_access(interaction, self.voice_id, self.user_id)
        if not voice or not roles:
            return
        if not voice.members:
            await interaction.response.send_message("В этом войсе сейчас нет участников", ephemeral=True)
            return
        await interaction.response.send_message("Выберите участника, которого нужно исключить из войса", view=KickMemberView(self.voice_id, self.user_id), ephemeral=True)

    @discord.ui.button(label="Войс открыт", style=discord.ButtonStyle.success)
    async def lock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        voice, roles = await voice_access(interaction, self.voice_id, self.user_id)
        if not voice or not roles:
            return
        await interaction.response.defer()
        self.closed = not self.closed
        await voice.set_permissions(
            interaction.guild.default_role,
            view_channel=True,
            connect=not self.closed,
            send_messages=True,
            read_message_history=True,
            reason=f"Войс изменён {interaction.user}",
        )
        owner_member = interaction.guild.get_member(self.user_id)
        if owner_member is None:
            try:
                owner_member = await interaction.guild.fetch_member(self.user_id)
            except discord.NotFound:
                pass
        if owner_member is not None:
            await voice.set_permissions(owner_member, view_channel=True, connect=True, reason="Доступ создателю временного войса")
        await voice.set_permissions(roles[2], connect=True, view_channel=True)
        await voice.set_permissions(roles[3], connect=True, view_channel=True)
        bot.store.close_voice(self.voice_id, self.closed)
        button.label = "Войс закрыт" if self.closed else "Войс открыт"
        button.style = discord.ButtonStyle.danger if self.closed else discord.ButtonStyle.success
        await interaction.edit_original_response(view=self)


def voice_control_embed() -> discord.Embed:
    return discord.Embed(
        title="Управление войсом",
        description="Переименовывайте войс, меняйте лимит, закрывайте доступ и исключайте участников. Управлять может только создатель войса, хелпер или администратор",
        colour=colour(VOICE_CONTROL_COLOR_HTML),
    )


async def create_voice(member: discord.Member) -> None:
    roles = await bot.roles(member.guild)
    category = member.guild.get_channel(VOICE_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        return
    overwrites = {
        member.guild.default_role: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            send_messages=True,
            read_message_history=True,
        ),
        roles[2]: discord.PermissionOverwrite(view_channel=True, connect=True),
        roles[3]: discord.PermissionOverwrite(view_channel=True, connect=True),
    }
    voice = await member.guild.create_voice_channel(f"Войс | {member.display_name}"[:100], category=category, overwrites=overwrites, reason=f"Временный войс для {member}")
    await member.move_to(voice, reason="Перемещение в созданный войс")
    await voice.send(embed=voice_control_embed(), view=VoiceControls(voice.id, member.id, False))
    bot.store.add_voice(voice.id, member.id)


async def remove_voice(channel: discord.VoiceChannel) -> None:
    if channel.members or channel.id not in {voice_id for voice_id, _, _ in bot.store.voices()}:
        return
    bot.store.remove_voice(channel.id)
    await channel.delete(reason="Временный войс пуст")


# ============================================================
# КАНАЛЫ СТАТИСТИКИ
# ============================================================


def statistics_setting_key(guild_id: int, statistic: str) -> str:
    return f"statistics_channel:{guild_id}:{statistic}"


def find_statistics_channel(
    guild: discord.Guild,
    statistic: str,
    prefixes: tuple[str, ...],
) -> discord.VoiceChannel | None:
    stored_id = bot.store.get(statistics_setting_key(guild.id, statistic))
    stored_channel = guild.get_channel(stored_id) if stored_id else None
    if isinstance(stored_channel, discord.VoiceChannel):
        return stored_channel
    return next(
        (
            channel
            for channel in guild.voice_channels
            if any(channel.name.startswith(prefix) for prefix in prefixes)
        ),
        None,
    )


async def ensure_statistics_channel(
    guild: discord.Guild,
    statistic: str,
    name: str,
    prefixes: tuple[str, ...],
) -> discord.VoiceChannel:
    channel = find_statistics_channel(guild, statistic, prefixes)
    if channel is None:
        channel = await guild.create_voice_channel(
            name,
            overwrites={
                guild.default_role: discord.PermissionOverwrite(
                    view_channel=True,
                    connect=False,
                ),
            },
            reason="Создание канала статистики",
        )
    bot.store.set(statistics_setting_key(guild.id, statistic), channel.id)

    everyone_overwrite = channel.overwrites_for(guild.default_role)
    if everyone_overwrite.view_channel is not True or everyone_overwrite.connect is not False:
        everyone_overwrite.view_channel = True
        everyone_overwrite.connect = False
        await channel.set_permissions(
            guild.default_role,
            overwrite=everyone_overwrite,
            reason="Настройка доступа к каналу статистики",
        )
    if channel.name != name:
        await channel.edit(name=name, reason="Обновление статистики сервера")
    return channel


async def minecraft_online_name() -> str:
    try:
        response = await rcon_command("list")
    except RconError:
        return f"{STATISTICS_ONLINE_PREFIX} недоступен"
    patterns = (
        r"There are\s+(\d+)\s+of a max of\s+(\d+)\s+players online",
        r"(?:онлайн|online)[^\d]*(\d+)\s*(?:из|/|of)\s*(\d+)",
        r"\b(\d+)\s*/\s*(\d+)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, response, flags=re.IGNORECASE)
        if match:
            online, maximum = map(int, match.groups())
            bot.store.update_daily_maximum("peak_online", online)
            return f"{STATISTICS_ONLINE_PREFIX} {online}/{maximum}"
    logging.warning("Не удалось определить онлайн из ответа Minecraft: %s", response)
    return f"{STATISTICS_ONLINE_PREFIX} неизвестно"


async def update_statistics_channels(guild: discord.Guild) -> None:
    if guild.id != GUILD_ID:
        return
    async with bot.statistics_lock:
        if not guild.chunked:
            try:
                await guild.chunk(cache=True)
            except (discord.HTTPException, discord.ClientException):
                logging.exception("Не удалось загрузить список участников для статистики сервера %s", guild.id)

        player_role = guild.get_role(PLAYER_ROLE_ID)
        member_count = sum(not member.bot for member in guild.members)
        player_count = sum(not member.bot for member in player_role.members) if player_role else 0
        online_name = await minecraft_online_name()
        specifications = (
            ("ip", STATISTICS_IP_NAME, ("IP:",)),
            ("members", f"{STATISTICS_MEMBERS_PREFIX} {member_count}", (STATISTICS_MEMBERS_PREFIX, "Участники:")),
            ("players", f"{STATISTICS_PLAYERS_PREFIX} {player_count}", (STATISTICS_PLAYERS_PREFIX,)),
            ("online", online_name, (STATISTICS_ONLINE_PREFIX,)),
        )
        for statistic, name, prefixes in specifications:
            await ensure_statistics_channel(guild, statistic, name, prefixes)


async def delayed_statistics_update(guild: discord.Guild) -> None:
    try:
        await asyncio.sleep(STATISTICS_UPDATE_DELAY_SECONDS)
        await update_statistics_channels(guild)
    except asyncio.CancelledError:
        raise
    except Exception:
        logging.exception("Не удалось обновить каналы статистики сервера %s", guild.id)
    finally:
        current_task = asyncio.current_task()
        if bot.statistics_update_tasks.get(guild.id) is current_task:
            bot.statistics_update_tasks.pop(guild.id, None)


def schedule_statistics_update(guild: discord.Guild) -> None:
    current_task = bot.statistics_update_tasks.get(guild.id)
    if current_task is None or current_task.done():
        bot.statistics_update_tasks[guild.id] = asyncio.create_task(delayed_statistics_update(guild))


@tasks.loop(minutes=10)
async def statistics_refresh_loop() -> None:
    for guild in bot.guilds:
        try:
            await update_statistics_channels(guild)
        except Exception:
            logging.exception("Не удалось проверить каналы статистики сервера %s", guild.id)


@statistics_refresh_loop.before_loop
async def before_statistics_refresh_loop() -> None:
    await bot.wait_until_ready()


# ============================================================
# СОБЫТИЯ
# ============================================================


@bot.event
async def on_member_join(member: discord.Member) -> None:
    first_join = bot.store.first_join(member.guild.id, member.id)
    if first_join:
        guest, _, _, _ = await bot.roles(member.guild)
        await member.add_roles(guest, reason="Первый вход на сервер")
        if not member.bot:
            bot.store.increment_daily_metric("new_members")
    roles = await moderation_roles(member.guild)
    try:
        await restore_member_punishments(member, roles)
    except discord.HTTPException:
        logging.exception("Не удалось восстановить наказания пользователя %s после входа", member.id)
    schedule_statistics_update(member.guild)


@bot.event
async def on_member_remove(member: discord.Member) -> None:
    schedule_statistics_update(member.guild)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member) -> None:
    had_player_role = before.get_role(PLAYER_ROLE_ID) is not None
    has_player_role = after.get_role(PLAYER_ROLE_ID) is not None
    if had_player_role != has_player_role:
        schedule_statistics_update(after.guild)


@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel) -> None:
    if channel.guild.id != GUILD_ID:
        return
    try:
        roles = await moderation_roles(channel.guild)
        await apply_mute_overwrite(channel, roles["mute"])
        for user_id in bot.store.active_user_ids(channel.guild.id, "mute"):
            member = channel.guild.get_member(user_id)
            if member is not None:
                await apply_member_mute_overwrite(channel, member)
    except discord.HTTPException:
        logging.exception("Не удалось настроить роль мута в новом канале %s", channel.id)


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot or not message.guild:
        return
    if message.channel.id == SPAM_PROTECTION_CHANNEL_ID:
        try:
            await message.delete()
            await message.author.ban(reason="Сообщение в защищённом от спама канале", delete_message_seconds=0)
            result = "сообщение удалено, пользователь заблокирован"
        except discord.Forbidden:
            result = "не удалось заблокировать: недостаточно прав"
        await bot.log(message.guild, "Сработала защита от спама", {
            "Пользователь": f"{message.author.mention} ({message.author})",
            "Канал": f"<#{SPAM_PROTECTION_CHANNEL_ID}>",
            "Сообщение": message.content or "Без текста",
            "Результат": result,
        })
        return
    await bot.process_commands(message)


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
    if after.channel and after.channel.id == VOICE_CREATOR_CHANNEL_ID and before.channel != after.channel:
        try:
            await create_voice(member)
        except discord.HTTPException:
            logging.exception("Не удалось создать временный войс")
    if before.channel:
        await remove_voice(before.channel)


@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel) -> None:
    if isinstance(channel, discord.TextChannel):
        bot.store.remove_ticket_assignment(channel.id)
    if isinstance(channel, discord.VoiceChannel):
        bot.store.remove_voice(channel.id)
        schedule_statistics_update(channel.guild)


@bot.tree.command(name="установка", description="Проверить панели бота")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.default_permissions(administrator=True)
async def setup(interaction: discord.Interaction) -> None:
    if not interaction.guild or not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Команда доступна только администраторам", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    await bot.roles(interaction.guild)
    await panels(interaction.guild)
    await restore(interaction.guild)
    await update_statistics_channels(interaction.guild)
    await update_moderator_documentation(interaction.guild)
    await interaction.followup.send("Панели, каналы статистики, документация и активные кнопки проверены", ephemeral=True)


async def main() -> None:
    if not TOKEN:
        raise RuntimeError("Не задан DISCORD_TOKEN.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
