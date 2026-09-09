from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


# ============================================================
# НАСТРОЙКИ
# ============================================================

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN", "")

APPLICATION_PANEL_CHANNEL_ID = 1486337529954304080
HELP_PANEL_CHANNEL_ID = 1495766775734865930
APPLICATION_CATEGORY_ID = 1500023409952686190
TICKET_CATEGORY_ID = 1485653736335605841
SPAM_PROTECTION_CHANNEL_ID = 1485655876193882363
LOG_CHANNEL_ID = 1486338493029548094
VOICE_CREATOR_CHANNEL_ID = 1498318412080746556
VOICE_CATEGORY_ID = 1485288483881746623
GUEST_ROLE_ID = 1485642937860620518
PLAYER_ROLE_ID = 1485642979556327445
HELPER_ROLE_ID = 1486339038402183338
ADMIN_ROLE_ID = 1486338979300380753
GUILD_ID = 1484230925473546292

APPLICATION_PANEL_COLOR_HTML = "#FFD700"
APPLICATION_EMBED_COLOR_HTML = "#FFD700"
HELP_PANEL_COLOR_HTML = "#FFD700"
TICKET_EMBED_COLOR_HTML = "#FFD700"
VOICE_CONTROL_COLOR_HTML = "#FFD700"
SPAM_WARNING_COLOR_HTML = "#ED4245"
APPLICATION_REJECTED_COLOR_HTML = "#ED4245"
APPLICATION_ACCEPTED_COLOR_HTML = "#57F287"
LOG_EMBED_COLOR_HTML = "#5865F2"

DB_FILE = "bot_state.sqlite3"
APP_PREFIX = "application_owner="
TICKET_PREFIX = "ticket_owner="
GAME_RULES = (
    "**1.** Запрещён гриф в любом виде: кража вещей, разрушение территорий, убийство игроков и питомцев\n"
    "**1.1.** Запрещены ловушки и механизмы, созданные для вреда игрокам\n"
    "**1.2.** Запрещено портить игровой мир: недорубать деревья, строить столбы и блоки для прыжков\n"
    "**1.3.** РП-PvP и соревновательное PvP проводятся по договорённости участников и фиксируются в игровой книге\n"
    "**1.4.** Запрещено нападать на администратора при исполнении обязанностей\n\n"
    "**2.** Запрещено использовать и хранить модификации, дающие преимущество в игре\n"
    "**3.** Запрещено мешать проведению ивентов и работе спавна\n"
    "**4.** Запрещено препятствовать работе администрации, делать ложные вызовы и вводить в заблуждение\n"
    "**5.** Запрещены преследование и слежка за игроками\n"
    "**6.** Запрещены лаг-машины и механизмы с большой нагрузкой на сервер\n"
    "**7.** Запрещено вычислять, использовать и распространять сид мира\n"
    "**8.** Запрещено использовать лазейки, багоюз и обходить наказания. О багах сообщайте в канал <#1495766775734865930>\n"
    "**9.** Занятая территория обозначается пунктирной линией из неприродных блоков с табличками владельца"
)


# ============================================================
# ХРАНИЛИЩЕ
# ============================================================


class Store:
    def __init__(self) -> None:
        self.db = sqlite3.connect(DB_FILE)
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS members (guild_id INTEGER, user_id INTEGER, PRIMARY KEY(guild_id,user_id));"
            "CREATE TABLE IF NOT EXISTS voices (voice_id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, closed INTEGER NOT NULL DEFAULT 0);"
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


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================


def owner(channel: discord.abc.GuildChannel, prefix: str) -> int | None:
    match = re.search(rf"{prefix}(\d+)", getattr(channel, "topic", "") or "")
    return int(match.group(1)) if match else None


def colour(html: str) -> discord.Colour:
    return discord.Colour(int(html.removeprefix("#"), 16))


def channel_name(prefix: str, member: discord.Member) -> str:
    name = re.sub(r"[^a-z0-9_-]", "", member.name.lower().replace(" ", "-"))
    return f"{prefix}-{name or member.id}"[:100]


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

    async def log(self, guild: discord.Guild, action: str, fields: dict[str, object] | None = None) -> None:
        logging.info("%s | %s", action, fields or {})
        channel = guild.get_channel(LOG_CHANNEL_ID)
        if isinstance(channel, discord.TextChannel):
            try:
                embed = discord.Embed(title=f"Лог • {action}", colour=colour(LOG_EMBED_COLOR_HTML), timestamp=datetime.now(timezone.utc))
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

    async def on_ready(self) -> None:
        if self.started:
            return
        self.started = True
        for guild in self.guilds:
            try:
                await self.roles(guild)
                await panels(guild)
                await restore(guild)
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
    except discord.Forbidden:
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
    ticket_category = guild.get_channel(TICKET_CATEGORY_ID)
    if isinstance(ticket_category, discord.CategoryChannel):
        for channel in ticket_category.text_channels:
            user_id = owner(channel, TICKET_PREFIX)
            if user_id:
                bot.add_view(TicketControls(user_id))
    for voice_id, user_id, closed in bot.store.voices():
        if isinstance(guild.get_channel(voice_id), discord.VoiceChannel):
            bot.add_view(VoiceControls(voice_id, user_id, closed))
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
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            roles[2]: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            roles[3]: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        channel = await interaction.guild.create_text_channel(channel_name("заявка", interaction.user), category=category, overwrites=overwrites, topic=f"{APP_PREFIX}{interaction.user.id};pending", reason=f"Заявка от {interaction.user}")
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
        await channel.send(content=f"{interaction.user.mention} {roles[2].mention} {roles[3].mention}", embed=embed, view=ApplicationDecision(interaction.user.id), allowed_mentions=discord.AllowedMentions(users=True, roles=True))
        await bot.log(interaction.guild, "Новая заявка", {
            "Пользователь": f"{interaction.user.mention} ({interaction.user})",
            "Никнейм": self.nickname.value,
            "Возраст": self.age.value,
            "Кратко о себе": self.about.value,
            "Откуда узнали": self.source.value or "Не указано",
        })
        await interaction.response.send_message("Заявка отправлена. Ожидайте решение в личных сообщениях", ephemeral=True)


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
        embed = discord.Embed(title="Правила игры на сервере", description=GAME_RULES, colour=colour(APPLICATION_PANEL_COLOR_HTML))
        await interaction.response.send_message("Перед подачей заявки ознакомьтесь с правилами", embed=embed, view=GameRulesView(interaction.user.id), ephemeral=True)


class RejectionForm(discord.ui.Modal, title="Отклонение заявки"):
    reason = discord.ui.TextInput(label="Причина отказа", required=True, style=discord.TextStyle.paragraph, max_length=1000)

    def __init__(self, user_id: int, message_id: int) -> None:
        super().__init__()
        self.user_id = user_id
        self.message_id = message_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await staff(interaction) or not interaction.guild or not isinstance(interaction.user, discord.Member) or not isinstance(interaction.channel, discord.TextChannel):
            return
        applicant = interaction.guild.get_member(self.user_id)
        if applicant:
            await dm(applicant, discord.Embed(title="Заявка отклонена", description=f"Причина: {self.reason.value}\nОтклонил: {interaction.user.mention}", colour=colour(APPLICATION_REJECTED_COLOR_HTML)))
        await interaction.channel.edit(topic=f"{APP_PREFIX}{self.user_id};rejected", reason=f"Заявка отклонена {interaction.user}")
        try:
            await (await interaction.channel.fetch_message(self.message_id)).edit(view=None)
        except discord.NotFound:
            pass
        await bot.log(interaction.guild, "Заявка отклонена", {
            "Модератор": interaction.user.mention,
            "Пользователь": f"<@{self.user_id}>",
            "Причина": self.reason.value,
        })
        await interaction.response.send_message("Заявка отклонена", ephemeral=True)
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
        await applicant.add_roles(roles[1], reason=f"Заявка одобрена {interaction.user}")
        await applicant.remove_roles(roles[0], reason=f"Заявка одобрена {interaction.user}")
        await dm(applicant, discord.Embed(title="Заявка принята", description=f"Заявку принял: {interaction.user.mention}\nДобро пожаловать на сервер! Приятной игры", colour=colour(APPLICATION_ACCEPTED_COLOR_HTML)))
        await interaction.channel.edit(topic=f"{APP_PREFIX}{self.user_id};accepted", reason=f"Заявка одобрена {interaction.user}")
        if interaction.message:
            await interaction.message.edit(view=None)
        await bot.log(interaction.guild, "Заявка принята", {
            "Модератор": interaction.user.mention,
            "Пользователь": applicant.mention,
        })
        await interaction.response.send_message("Заявка принята: игрок выдан, гость снят", ephemeral=True)
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
    "bug": ("Баг-репорт", (("Ваш никнейм", True), ("Описание бага", True), ("Как повторить баг?", True))),
    "login": ("Проблема со входом", (("Ваш никнейм", True), ("Что именно не работает?", True), ("Когда возникла проблема?", False))),
    "player": ("Жалоба на игрока", (("Ваш никнейм", True), ("Никнейм нарушителя", True), ("Что случилось?", True))),
    "territory": ("Вопрос о территории", (("Ваш никнейм", True), ("Название территории или координаты", True), ("Ваш вопрос", True))),
    "donation": ("Проблема с донатом", (("Ваш никнейм", True), ("Что было приобретено?", True), ("Описание проблемы", True), ("Номер платежа (если есть)", False))),
    "admin": ("Жалоба на администратора", (("Ваш никнейм", True), ("Никнейм администратора", True), ("Что случилось?", True))),
    "other": ("Другое", (("Ваш никнейм", True), ("Опишите ситуацию", True))),
}


class HelpForm(discord.ui.Modal):
    def __init__(self, kind: str) -> None:
        title, fields = FORMS[kind]
        super().__init__(title=title[:45])
        self.kind = kind
        self.inputs: list[discord.ui.TextInput] = []
        long = {"Описание бага", "Как повторить баг?", "Что случилось?", "Что именно не работает?", "Ваш вопрос", "Описание проблемы", "Опишите ситуацию"}
        for label, required in fields:
            item = discord.ui.TextInput(label=label, required=required, style=discord.TextStyle.paragraph if label in long else discord.TextStyle.short, max_length=1000)
            self.inputs.append(item)
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Обращение можно создать только на сервере", ephemeral=True)
            return
        roles = await bot.roles(interaction.guild)
        category = interaction.guild.get_channel(TICKET_CATEGORY_ID)
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message("Категория обращений не найдена", ephemeral=True)
            return
        if any(owner(channel, TICKET_PREFIX) == interaction.user.id for channel in category.text_channels):
            await interaction.response.send_message("У вас уже есть открытое обращение", ephemeral=True)
            return
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            roles[2]: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True),
            roles[3]: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True),
        }
        channel = await interaction.guild.create_text_channel(channel_name("обращение", interaction.user), category=category, overwrites=overwrites, topic=f"{TICKET_PREFIX}{interaction.user.id};{self.kind}", reason=f"Обращение от {interaction.user}")
        title, fields = FORMS[self.kind]
        embed = discord.Embed(title=title, colour=colour(TICKET_EMBED_COLOR_HTML), timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Автор", value=interaction.user.mention, inline=False)
        log_fields: dict[str, object] = {
            "Пользователь": interaction.user.mention,
            "Тема обращения": title,
        }
        for (label, _), item in zip(fields, self.inputs):
            value = item.value or "Не указано"
            embed.add_field(name=label, value=value, inline=False)
            log_fields[label] = value
        await channel.send(content=f"{interaction.user.mention} {roles[2].mention} {roles[3].mention}", embed=embed, view=TicketControls(interaction.user.id), allowed_mentions=discord.AllowedMentions(users=True, roles=True))
        await bot.log(interaction.guild, "Новое обращение", log_fields)
        await interaction.response.send_message(f"Обращение создано: {channel.mention}", ephemeral=True)


class HelpSelect(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(placeholder="Выберите тему обращения", custom_id="help:select", options=[discord.SelectOption(label=title, value=key) for key, (title, _) in FORMS.items()])

    async def callback(self, interaction: discord.Interaction) -> None:
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


@bot.tree.command(name="add", description="Добавить пользователя в текущее обращение")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(user="Пользователь, которому нужно открыть доступ")
async def add_to_ticket(interaction: discord.Interaction, user: discord.Member) -> None:
    roles = await staff(interaction)
    if not roles or not interaction.guild or not is_ticket(interaction.channel):
        if roles:
            await interaction.response.send_message("Команду можно использовать только в канале обращения", ephemeral=True)
        return
    await interaction.channel.set_permissions(
        user,
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        reason=f"Добавлен в обращение {interaction.user}",
    )
    await bot.log(interaction.guild, "Пользователь добавлен в обращение", {
        "Модератор": interaction.user.mention,
        "Пользователь": user.mention,
        "Тема обращения": ticket_topic(interaction.channel),
    })
    await interaction.response.send_message(f"{user.mention} добавлен в обращение", ephemeral=True)


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
# ВОЙСЫ
# ============================================================


class SlotsForm(discord.ui.Modal, title="Количество мест"):
    slots = discord.ui.TextInput(label="Сколько мест будет в войсе?", required=True, max_length=2, placeholder="1–99")

    def __init__(self, voice_id: int, user_id: int) -> None:
        super().__init__()
        self.voice_id = voice_id
        self.user_id = user_id

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
        await interaction.delete_original_response()


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


class VoiceControls(discord.ui.View):
    def __init__(self, voice_id: int, user_id: int, closed: bool) -> None:
        super().__init__(timeout=None)
        self.voice_id = voice_id
        self.user_id = user_id
        self.closed = closed
        self.slots.custom_id = f"voice:slots:{voice_id}:{user_id}"
        self.lock.custom_id = f"voice:lock:{voice_id}:{user_id}"
        self.lock.label = "Войс закрыт" if closed else "Войс открыт"
        self.lock.style = discord.ButtonStyle.danger if closed else discord.ButtonStyle.success

    @discord.ui.button(label="Кол-во мест", style=discord.ButtonStyle.primary)
    async def slots(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        voice, roles = await voice_access(interaction, self.voice_id, self.user_id)
        if voice and roles:
            await show_modal(interaction, SlotsForm(self.voice_id, self.user_id))

    @discord.ui.button(label="Войс открыт", style=discord.ButtonStyle.success)
    async def lock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        voice, roles = await voice_access(interaction, self.voice_id, self.user_id)
        if not voice or not roles:
            return
        self.closed = not self.closed
        await voice.set_permissions(interaction.guild.default_role, connect=False if self.closed else None, reason=f"Войс изменён {interaction.user}")
        await voice.set_permissions(roles[2], connect=True, view_channel=True)
        await voice.set_permissions(roles[3], connect=True, view_channel=True)
        bot.store.close_voice(self.voice_id, self.closed)
        button.label = "Войс закрыт" if self.closed else "Войс открыт"
        button.style = discord.ButtonStyle.danger if self.closed else discord.ButtonStyle.success
        await interaction.response.edit_message(view=self)


async def create_voice(member: discord.Member) -> None:
    roles = await bot.roles(member.guild)
    category = member.guild.get_channel(VOICE_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        return
    overwrites = {
        member.guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True),
        roles[2]: discord.PermissionOverwrite(view_channel=True, connect=True),
        roles[3]: discord.PermissionOverwrite(view_channel=True, connect=True),
    }
    voice = await member.guild.create_voice_channel(f"Войс | {member.display_name}"[:100], category=category, overwrites=overwrites, reason=f"Временный войс для {member}")
    await member.move_to(voice, reason="Перемещение в созданный войс")
    await voice.send(embed=discord.Embed(title="Управление войсом", description="Измените количество мест или закройте доступ. Управлять может создатель, хелпер или администратор", colour=colour(VOICE_CONTROL_COLOR_HTML)), view=VoiceControls(voice.id, member.id, False))
    bot.store.add_voice(voice.id, member.id)


async def remove_voice(channel: discord.VoiceChannel) -> None:
    if channel.members or channel.id not in {voice_id for voice_id, _, _ in bot.store.voices()}:
        return
    bot.store.remove_voice(channel.id)
    await channel.delete(reason="Временный войс пуст")


# ============================================================
# СОБЫТИЯ
# ============================================================


@bot.event
async def on_member_join(member: discord.Member) -> None:
    if bot.store.first_join(member.guild.id, member.id):
        guest, _, _, _ = await bot.roles(member.guild)
        await member.add_roles(guest, reason="Первый вход на сервер")
        await bot.log(member.guild, "Первый вход пользователя", {
            "Пользователь": f"{member.mention} ({member})",
            "Выданная роль": guest.mention,
        })
    else:
        await bot.log(member.guild, "Повторный вход пользователя", {
            "Пользователь": f"{member.mention} ({member})",
        })


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
    if isinstance(channel, discord.VoiceChannel):
        bot.store.remove_voice(channel.id)


@bot.tree.command(name="setup", description="Проверить панели бота")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.default_permissions(administrator=True)
async def setup(interaction: discord.Interaction) -> None:
    if not interaction.guild or not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Команда доступна только администраторам", ephemeral=True)
        return
    await bot.roles(interaction.guild)
    await panels(interaction.guild)
    await restore(interaction.guild)
    await interaction.response.send_message("Панели и активные кнопки проверены", ephemeral=True)


async def main() -> None:
    if not TOKEN:
        raise RuntimeError("Не задан DISCORD_TOKEN.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
