import discord
from discord import ui
from discord.ext import commands, tasks
import asyncio
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from openai import AsyncOpenAI
from collections import defaultdict

# Для RCON
from mcrcon import MCRcon, MCRconException

# ========================= НАСТРОЙКИ =========================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# ==================== RCON НАСТРОЙКИ ====================
RCON_HOST = os.getenv("RCON_HOST", "127.0.0.1")
RCON_PORT = int(os.getenv("RCON_PORT", 25575))
RCON_PASSWORD = os.getenv("RCON_PASSWORD")

if not TOKEN:
    raise ValueError("DISCORD_TOKEN не найден")

print(f"DISCORD_TOKEN: {'Да' if TOKEN else 'Нет'}")
print(f"OPENROUTER_API_KEY: {'Да' if OPENROUTER_API_KEY else 'Нет'}")
print(f"RCON: {RCON_HOST}:{RCON_PORT} — {'Настроен' if RCON_PASSWORD else 'ПАРОЛЬ НЕ УКАЗАН!'}")

# OpenRouter клиент
openrouter_client = AsyncOpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1"
) if OPENROUTER_API_KEY else None

# ==================== ID КАНАЛОВ И РОЛЕЙ ====================

APPLY_CHANNEL_ID = 1486337529954304080
TICKET_CATEGORY_ID = 1500023409952686190
SUPPORT_CHANNEL_ID = 1495766775734865930
SUPPORT_CATEGORY_ID = 1485653736335605841
LOG_CHANNEL_ID = 1486338493029548094
CONSOLE_CHANNEL_ID = 1486049017753239673
SPAM_PROTECTION_CHANNEL_ID = 1485655876193882363

STATS_IP_CHANNEL_ID = 1498252830358634526
STATS_MEMBERS_CHANNEL_ID = 1498252851799916716
STATS_PLAYERS_CHANNEL_ID = 1498252878937067690

SCREENSHOTS_CHANNEL_ID = 1485524643539456050
IRL_CHANNEL_ID = 1485524796342276117

ADMIN_ROLE_ID_1 = 1486338979300380753
ADMIN_ROLE_ID_2 = 1486339038402183338
PLAYER_ROLE_ID = 1485642979556327445
GUEST_ROLE_ID = 1485642937860620518

CREATE_VOICE_CHANNEL_ID = 1498318412080746556
TEMP_VOICE_CATEGORY_ID = 1485288483881746623
GUILD_ID = 1484230925473546292

# ============================================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.moderation = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ======================== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ========================

owner_to_channel = {}
channel_to_owner = {}
channel_is_private = {}

conversation_history = defaultdict(list)


def is_admin(member: discord.Member) -> bool:
    admin_ids = {ADMIN_ROLE_ID_1, ADMIN_ROLE_ID_2}
    return any(role.id in admin_ids for role in member.roles)

# ======================== RCON ========================

async def execute_rcon(command: str) -> str:
    """Выполняет команду через RCON"""
    if not RCON_PASSWORD:
        return "RCON не настроен (нет пароля в .env)"

    try:
        def sync_rcon_exec():
            with MCRcon(RCON_HOST, RCON_PASSWORD, port=RCON_PORT, timeout=5) as mcr:
                response = mcr.command(command)
                return response.strip() if response else "Выполнено"

        # Более безопасный способ для хостингов
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, sync_rcon_exec)
        
        print(f"[RCON] ✓ {command} → {response}")
        return response

    except MCRconException as e:
        print(f"[RCON ERROR] {e}")
        return f"RCON ошибка: {e}"
    except Exception as e:
        print(f"[RCON ERROR] {type(e).__name__}: {e}")
        return f"Не удалось подключиться к RCON: {str(e)[:120]}"


# ======================== OPENROUTER AI ========================

async def ask_openrouter(ticket_id: int, user_message: str) -> str:
    if not openrouter_client:
        return "OpenRouter временно недоступен"

    try:
        system_prompt = (
            "Ты дружелюбный и опытный помощник Minecraft-сервера AmberLand. "
            "Версия сервера: 1.21.11. Все игроки играют с ПК (Java Edition). "
            "Отвечай игрокам вежливо, кратко и на русском языке. "
            "Не грузи игроков сложной информацией, "
            "давай полезные советы по игре. Администраторы сервера - aTrapCW, Wakaja11"
        )

        conversation_history[ticket_id].append({"role": "user", "content": user_message})

        messages = [{"role": "system", "content": system_prompt}] + conversation_history[ticket_id]

        response = await openrouter_client.chat.completions.create(
            model="openrouter/free",
            messages=messages,
            temperature=0.7,
            max_tokens=750
        )

        ai_reply = response.choices[0].message.content.strip()

        conversation_history[ticket_id].append({"role": "assistant", "content": ai_reply})

        if len(conversation_history[ticket_id]) > 20:
            conversation_history[ticket_id] = conversation_history[ticket_id][-20:]

        return ai_reply

    except Exception as e:
        print(f"Ошибка OpenRouter: {e}")
        return f"Не удалось получить ответ от ИИ.\nОшибка: {str(e)[:150]}"


# ======================== СТАТИСТИКА ========================

@tasks.loop(minutes=10)
async def update_stats():
    if not bot.guilds:
        return
    guild = bot.guilds[0]

    ip_channel = guild.get_channel(STATS_IP_CHANNEL_ID)
    if ip_channel and ip_channel.name != "IP: amberland.fun":
        try:
            await ip_channel.edit(name="IP: amberland.fun", reason="Обновление статистики")
        except:
            pass

    members_count = len([m for m in guild.members if not m.bot])
    members_channel = guild.get_channel(STATS_MEMBERS_CHANNEL_ID)
    if members_channel:
        new_name = f"Участники: {members_count}"
        if members_channel.name != new_name:
            try:
                await members_channel.edit(name=new_name, reason="Обновление статистики")
            except:
                pass

    player_role = guild.get_role(PLAYER_ROLE_ID)
    players_count = len([m for m in guild.members if player_role in m.roles and not m.bot])
    players_channel = guild.get_channel(STATS_PLAYERS_CHANNEL_ID)
    if players_channel:
        new_name = f"Игроков: {players_count}"
        if players_channel.name != new_name:
            try:
                await players_channel.edit(name=new_name, reason="Обновление статистики")
            except:
                pass


# ======================== АВТО-РОЛЬ ========================

@bot.event
async def on_member_join(member: discord.Member):
    guest_role = member.guild.get_role(GUEST_ROLE_ID)
    if guest_role:
        try:
            await member.add_roles(guest_role, reason="Автоматическая роль при входе")
        except:
            pass


# ======================== ВРЕМЕННЫЕ ГОЛОСОВЫЕ КАНАЛЫ ========================

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member.bot:
        return

    guild = member.guild

    if after.channel and after.channel.id == CREATE_VOICE_CHANNEL_ID:
        if member.id in owner_to_channel:
            try:
                voice_channel = guild.get_channel(owner_to_channel[member.id])
                if voice_channel and isinstance(voice_channel, discord.VoiceChannel):
                    link = f"https://discord.com/channels/{GUILD_ID}/{voice_channel.id}"
                    embed = discord.Embed(
                        title="У тебя уже есть войс!",
                        description="Ты уже создал личный голосовой канал.",
                        color=discord.Color.red()
                    )
                    embed.add_field(name="Твой войс", value=f"[{voice_channel.name}]({link})", inline=False)
                    embed.set_footer(text="Нажми на название, чтобы перейти")
                    await member.send(embed=embed)
                    await member.move_to(voice_channel)
                    return
            except:
                pass

        category = guild.get_channel(TEMP_VOICE_CATEGORY_ID)
        channel_name = f"Войс | {member.display_name}"

        try:
            new_voice = await guild.create_voice_channel(
                name=channel_name,
                category=category,
                reason=f"Temp voice created by {member}"
            )

            await member.move_to(new_voice)

            owner_to_channel[member.id] = new_voice.id
            channel_to_owner[new_voice.id] = member.id
            channel_is_private[new_voice.id] = False

            embed = discord.Embed(
                title="Твой личный войс",
                description="Владелец\n" + member.mention + "\n\nНастрой свой войс с помощью кнопок ниже:",
                color=discord.Color(0xffbf00)
            )

            view = TempVoiceView(member.id, is_private=False)
            await new_voice.send(embed=embed, view=view)

        except Exception as e:
            print(f"Ошибка создания временного войса: {e}")
            try:
                await member.send("Не удалось создать войс. Обратитесь к администрации.")
            except:
                pass

    if before.channel and before.channel.id in channel_to_owner:
        voice_channel = before.channel
        if len(voice_channel.members) == 0:
            try:
                refreshed = guild.get_channel(voice_channel.id)
                if refreshed and len(refreshed.members) == 0:
                    await refreshed.delete(reason="Temp voice is empty")

                    owner_id = channel_to_owner.pop(voice_channel.id, None)
                    if owner_id and owner_id in owner_to_channel:
                        owner_to_channel.pop(owner_id, None)
                    channel_is_private.pop(voice_channel.id, None)
            except:
                owner_id = channel_to_owner.pop(voice_channel.id, None)
                if owner_id and owner_id in owner_to_channel:
                    owner_to_channel.pop(owner_id, None)
                channel_is_private.pop(voice_channel.id, None)


# ======================== МОДАЛЫ ========================

class ApplicationModal(ui.Modal, title="Заявка на сервер"):
    nickname = ui.TextInput(label="Никнейм в Minecraft", required=True, style=discord.TextStyle.short)
    age = ui.TextInput(label="Возраст", required=True, style=discord.TextStyle.short)
    experience = ui.TextInput(label="Опыт в Майнкрафте", required=True, style=discord.TextStyle.paragraph)
    source = ui.TextInput(label="Откуда знали о нас", required=False, style=discord.TextStyle.short)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        category = guild.get_channel(TICKET_CATEGORY_ID)
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.response.send_message("Категория для тикетов не найдена!", ephemeral=True)

        applicant = interaction.user
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            applicant: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        for role_id in [ADMIN_ROLE_ID_1, ADMIN_ROLE_ID_2]:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        ticket_channel = await guild.create_text_channel(
            name=f"заявка-{applicant.name.lower()}",
            category=category,
            overwrites=overwrites,
            reason=f"Заявка от {applicant}"
        )

        embed = discord.Embed(title="Новая заявка на сервер", color=discord.Color(0xffbf00))
        embed.add_field(name="Никнейм в Minecraft", value=self.nickname.value, inline=False)
        embed.add_field(name="Возраст", value=self.age.value, inline=True)
        embed.add_field(name="Опыт в Майнкрафте", value=self.experience.value, inline=False)
        embed.add_field(name="Откуда знали о нас", value=self.source.value or "Не указано", inline=False)
        embed.set_footer(text=f"Заявка от {applicant.id} | {applicant}")

        view = TicketView(applicant.id, self.nickname.value)
        admin_mentions = f"<@&{ADMIN_ROLE_ID_1}> <@&{ADMIN_ROLE_ID_2}>"

        await ticket_channel.send(content=f"{applicant.mention} {admin_mentions}", embed=embed, view=view)
        await interaction.response.send_message(f"Тикет успешно создан: {ticket_channel.mention}", ephemeral=True)


class SupportTicketModal(ui.Modal, title="Тикет поддержки"):
    nickname = ui.TextInput(label="Никнейм в Minecraft", required=True, style=discord.TextStyle.short)
    problem = ui.TextInput(label="Опишите вашу проблему", required=True, style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        category = guild.get_channel(SUPPORT_CATEGORY_ID)
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.response.send_message("Категория для тикетов поддержки не найдена!", ephemeral=True)

        applicant = interaction.user
        for channel in category.text_channels:
            if channel.name.startswith("тикет-") and str(applicant.id) in channel.name:
                return await interaction.response.send_message(f"У вас уже открыт тикет: {channel.mention}", ephemeral=True)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            applicant: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        for role_id in [ADMIN_ROLE_ID_1, ADMIN_ROLE_ID_2]:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        ticket_channel = await guild.create_text_channel(
            name=f"тикет-{applicant.name.lower()}-{applicant.id}",
            category=category,
            overwrites=overwrites,
            reason=f"Тикет поддержки от {applicant}"
        )

        embed = discord.Embed(
            title="Новый тикет поддержки",
            description="Администрация скоро ответит вам.\nВы можете вести диалог с ИИ через кнопку «Спросить ИИ».",
            color=discord.Color(0xffbf00)
        )
        embed.add_field(name="Никнейм", value=self.nickname.value, inline=False)
        embed.add_field(name="Проблема", value=self.problem.value, inline=False)
        embed.set_footer(text=f"Создал {applicant.id} | {applicant}")

        view = SupportTicketView(applicant.id, self.problem.value, ticket_channel.id)
        await ticket_channel.send(content=f"{applicant.mention} <@&{ADMIN_ROLE_ID_1}> <@&{ADMIN_ROLE_ID_2}>", embed=embed, view=view)
        await interaction.response.send_message(f"Тикет поддержки успешно создан: {ticket_channel.mention}", ephemeral=True)


class AskAIModal(ui.Modal, title="Спросить ИИ"):
    question = ui.TextInput(label="Ваш вопрос", style=discord.TextStyle.paragraph, required=True, max_length=500)

    def __init__(self, ticket_id: int):
        super().__init__()
        self.ticket_id = ticket_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        async with interaction.channel.typing():
            ai_answer = await ask_openrouter(self.ticket_id, self.question.value)

        embed = discord.Embed(
            title="ИИ ответил:",
            description=ai_answer,
            color=discord.Color(0x00ccff)
        )

        await interaction.followup.send(embed=embed)


# ======================== КНОПКИ ========================

class ApplyView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Подать заявку", style=discord.ButtonStyle.primary, custom_id="apply_button_persistent")
    async def apply_button(self, interaction: discord.Interaction, button: ui.Button):
        member = interaction.user
        player_role = interaction.guild.get_role(PLAYER_ROLE_ID)
        if player_role and player_role in member.roles:
            embed = discord.Embed(
                title="Вы уже на сервере",
                description="У вас уже есть роль Игрок. Повторная подача заявки не требуется.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        modal = ApplicationModal()
        await interaction.response.send_modal(modal)


class SupportApplyView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Создать тикет поддержки", style=discord.ButtonStyle.primary, custom_id="support_ticket_button_persistent")
    async def support_button(self, interaction: discord.Interaction, button: ui.Button):
        modal = SupportTicketModal()
        await interaction.response.send_modal(modal)


class TicketView(ui.View):
    def __init__(self, applicant_id: int, nickname: str):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.nickname = nickname

    @ui.button(label="Принять", style=discord.ButtonStyle.success, custom_id="accept_ticket_persistent")
    async def accept_button(self, interaction: discord.Interaction, button: ui.Button):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("У вас нет прав администратора.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        admin = interaction.user
        nickname = self.nickname.strip()

        # Добавление в whitelist через RCON
        rcon_result = await execute_rcon(f"whitelist add {nickname}")

        # Выдача роли
        try:
            member = await interaction.guild.fetch_member(self.applicant_id)
            player_role = interaction.guild.get_role(PLAYER_ROLE_ID)
            guest_role = interaction.guild.get_role(GUEST_ROLE_ID)

            if member:
                if guest_role and guest_role in member.roles:
                    await member.remove_roles(guest_role, reason="Заявка одобрена")
                if player_role:
                    await member.add_roles(player_role, reason="Одобрена заявка на сервер")
        except:
            pass

        # Сообщение игроку
        try:
            user = await bot.fetch_user(self.applicant_id)
            embed = discord.Embed(title="Ваша заявка одобрена!", description="Поздравляем! Вы приняты на наш Minecraft сервер.", color=discord.Color.green())
            embed.add_field(name="Никнейм", value=nickname, inline=False)
            embed.add_field(name="Администратор", value=f"{admin}", inline=False)
            embed.add_field(name="Что дальше?", value="Зайди на сервер по IP: `amberland.fun`")
            await user.send(embed=embed)
        except:
            pass

        # Логи
        log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(title="Заявка принята", color=discord.Color.green(), timestamp=discord.utils.utcnow())
            embed.add_field(name="Игрок", value=f"<@{self.applicant_id}>", inline=False)
            embed.add_field(name="Никнейм", value=nickname, inline=False)
            embed.add_field(name="Администратор", value=f"{admin} ({admin.id})", inline=False)
            embed.add_field(name="RCON", value=rcon_result, inline=False)
            await log_channel.send(embed=embed)

        disabled_view = ui.View()
        disabled_view.add_item(ui.Button(label="Принять", style=discord.ButtonStyle.success, disabled=True))
        disabled_view.add_item(ui.Button(label="Отклонить", style=discord.ButtonStyle.danger, disabled=True))

        await interaction.edit_original_response(content=f"Заявка принята | {rcon_result}", view=disabled_view)
        await interaction.followup.send("Заявка успешно одобрена!", ephemeral=True)

        try:
            await asyncio.sleep(3)
            await interaction.channel.delete(reason=f"Заявка принята администратором {admin}")
        except:
            pass

    @ui.button(label="Отклонить", style=discord.ButtonStyle.danger, custom_id="reject_ticket_persistent")
    async def reject_button(self, interaction: discord.Interaction, button: ui.Button):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("У вас нет прав администратора.", ephemeral=True)
        modal = RejectModal(self.applicant_id, self.nickname)
        await interaction.response.send_modal(modal)


class RejectModal(ui.Modal, title="Причина отказа"):
    reason = ui.TextInput(label="Причина отказа", style=discord.TextStyle.paragraph, required=True)

    def __init__(self, applicant_id: int, nickname: str):
        super().__init__()
        self.applicant_id = applicant_id
        self.nickname = nickname

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("Нет прав.", ephemeral=True)

        admin = interaction.user
        reason_text = self.reason.value

        try:
            applicant = await bot.fetch_user(self.applicant_id)
            embed = discord.Embed(title="Ваша заявка была отклонена", color=discord.Color.red())
            embed.add_field(name="Администратор", value=f"{admin} ({admin.id})", inline=False)
            embed.add_field(name="Причина", value=reason_text, inline=False)
            await applicant.send(embed=embed)
        except:
            pass

        log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(title="Заявка отклонена", color=discord.Color.red(), timestamp=discord.utils.utcnow())          
            embed.add_field(name="Игрок", value=f"<@{self.applicant_id}>", inline=False)
            embed.add_field(name="Никнейм", value=self.nickname, inline=False)
            embed.add_field(name="Администратор", value=f"{admin} ({admin.id})", inline=False)
            embed.add_field(name="Причина", value=reason_text, inline=False)
            await log_channel.send(embed=embed)

        disabled_view = ui.View()
        disabled_view.add_item(ui.Button(label="Принять", style=discord.ButtonStyle.success, disabled=True))
        disabled_view.add_item(ui.Button(label="Отклонить", style=discord.ButtonStyle.danger, disabled=True))

        await interaction.response.edit_message(content=f"Заявка отклонена\nОтклонил: {admin}", view=disabled_view)
        await interaction.followup.send("Заявка отклонена.", ephemeral=True)

        try:
            await asyncio.sleep(2)
            await interaction.channel.delete(reason=f"Заявка отклонена администратором {admin}")
        except:
            pass


class SupportTicketView(ui.View):
    def __init__(self, applicant_id: int, problem: str, ticket_id: int):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.problem = problem
        self.ticket_id = ticket_id

    @ui.button(label="Моя проблема решена", style=discord.ButtonStyle.success, custom_id="solve_ticket_persistent")
    async def solve_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.applicant_id:
            return await interaction.response.send_message("Только создатель тикета может нажать эту кнопку.", ephemeral=True)

        if self.ticket_id in conversation_history:
            del conversation_history[self.ticket_id]

        player = interaction.user
        log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(title="Тикет закрыт игроком", color=discord.Color(0xffbf00), timestamp=discord.utils.utcnow())
            embed.add_field(name="Игрок", value=f"{player} ({player.id})", inline=False)
            embed.add_field(name="Проблема", value=self.problem, inline=False)
            await log_channel.send(embed=embed)

        disabled_view = ui.View()
        disabled_view.add_item(ui.Button(label="Моя проблема решена", style=discord.ButtonStyle.success, disabled=True))
        disabled_view.add_item(ui.Button(label="Закрыть тикет", style=discord.ButtonStyle.danger, disabled=True))

        await interaction.response.edit_message(content="Тикет закрыт вами. Спасибо за обращение!", view=disabled_view)

        try:
            await asyncio.sleep(3)
            await interaction.channel.delete(reason=f"Тикет закрыт игроком {player}")
        except:
            pass

    @ui.button(label="Закрыть тикет", style=discord.ButtonStyle.danger, custom_id="close_ticket_persistent")
    async def close_button(self, interaction: discord.Interaction, button: ui.Button):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("У вас нет прав администратора.", ephemeral=True)
        
        modal = AdminSolutionModal(self.applicant_id, self.problem)
        await interaction.response.send_modal(modal)

    @ui.button(label="Спросить ИИ", style=discord.ButtonStyle.gray, custom_id="ask_ai_button")
    async def ask_ai_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(AskAIModal(self.ticket_id))


class AdminSolutionModal(ui.Modal, title="Решение администрации"):
    solution = ui.TextInput(label="Решение администрации", style=discord.TextStyle.paragraph, required=True,
                            placeholder="Опишите, что было сделано...")

    def __init__(self, applicant_id: int, problem: str):
        super().__init__()
        self.applicant_id = applicant_id
        self.problem = problem

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("Нет прав.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        admin = interaction.user
        solution_text = self.solution.value

        log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(title="Тикет поддержки закрыт", color=discord.Color(0xffbf00), timestamp=discord.utils.utcnow())
            embed.add_field(name="Игрок", value=f"<@{self.applicant_id}>", inline=False)
            embed.add_field(name="Проблема", value=self.problem, inline=False)
            embed.add_field(name="Решение администрации", value=solution_text, inline=False)
            embed.add_field(name="Закрыл", value=f"{admin} ({admin.id})", inline=False)
            await log_channel.send(embed=embed)

        try:
            user = await bot.fetch_user(self.applicant_id)
            embed = discord.Embed(
                title="Ваш тикет поддержки закрыт",
                description="Администрация закрыла ваше обращение.",
                color=discord.Color(0xffbf00)
            )
            embed.add_field(name="Решение администрации", value=solution_text, inline=False)
            embed.add_field(name="Администратор", value=f"{admin}", inline=False)
            await user.send(embed=embed)
        except:
            pass

        try:
            await interaction.edit_original_response(
                content=f"Тикет закрыт администратором {admin}\nРешение: {solution_text[:200]}...",
                view=None
            )
        except:
            pass

        await interaction.followup.send("Тикет закрыт с решением.", ephemeral=True)

        try:
            await asyncio.sleep(3)
            await interaction.channel.delete(reason=f"Тикет закрыт администратором {admin}")
        except:
            pass


class TempVoiceView(ui.View):
    def __init__(self, owner_id: int, is_private: bool = False):
        super().__init__(timeout=None)
        self.owner_id = owner_id
        self.is_private = is_private

    @ui.button(label="Название войса", style=discord.ButtonStyle.primary, custom_id="tempvoice_rename", row=0)
    async def rename_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Только создатель войса может менять настройки.", ephemeral=True)

        class RenameModal(ui.Modal, title="Изменить название войса"):
            new_name = ui.TextInput(label="Новое название", required=True, max_length=100)

            async def on_submit(self, modal_inter: discord.Interaction):
                try:
                    if isinstance(modal_inter.channel, discord.VoiceChannel):
                        await modal_inter.channel.edit(name=self.new_name.value[:100])
                        await modal_inter.response.send_message(f"Название изменено на {self.new_name.value}", ephemeral=True)
                except Exception:
                    await modal_inter.response.send_message("Не удалось изменить название.", ephemeral=True)

        await interaction.response.send_modal(RenameModal())

    @ui.button(label="Лимит участников", style=discord.ButtonStyle.primary, custom_id="tempvoice_limit", row=0)
    async def limit_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Только создатель войса может менять настройки.", ephemeral=True)

        class LimitModal(ui.Modal, title="Установить лимит"):
            limit = ui.TextInput(label="Максимум человек (0 = без лимита)", required=True, style=discord.TextStyle.short)

            async def on_submit(self, modal_inter: discord.Interaction):
                try:
                    lim = int(self.limit.value)
                    if lim < 0 or lim > 99:
                        raise ValueError
                    if isinstance(modal_inter.channel, discord.VoiceChannel):
                        await modal_inter.channel.edit(user_limit=lim if lim > 0 else 0)
                        text = "без ограничений" if lim == 0 else str(lim)
                        await modal_inter.response.send_message(f"Лимит установлен: {text}", ephemeral=True)
                except:
                    await modal_inter.response.send_message("Введи число от 0 до 99.", ephemeral=True)

        await interaction.response.send_modal(LimitModal())

    @ui.button(label="Сделать приватным", style=discord.ButtonStyle.primary, custom_id="tempvoice_private", row=1)
    async def private_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Только создатель войса может менять настройки.", ephemeral=True)
        if self.is_private:
            return await interaction.response.send_message("Войс уже приватный.", ephemeral=True)

        try:
            voice_channel: discord.VoiceChannel = interaction.channel
            overwrites = voice_channel.overwrites
            overwrites[interaction.guild.default_role] = discord.PermissionOverwrite(view_channel=False, connect=False)
            overwrites[interaction.user] = discord.PermissionOverwrite(
                view_channel=True, connect=True, speak=True, mute_members=True, deafen_members=True
            )
            for role_id in [ADMIN_ROLE_ID_1, ADMIN_ROLE_ID_2]:
                role = interaction.guild.get_role(role_id)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)

            await voice_channel.edit(overwrites=overwrites)
            channel_is_private[voice_channel.id] = True
            self.is_private = True

            await interaction.response.send_message("Войс сделан приватным.", ephemeral=True)
        except Exception:
            await interaction.response.send_message("Не удалось сделать войс приватным.", ephemeral=True)

    @ui.button(label="Сделать публичным", style=discord.ButtonStyle.primary, custom_id="tempvoice_public", row=1)
    async def public_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Только создатель войса может менять настройки.", ephemeral=True)
        if not self.is_private:
            return await interaction.response.send_message("Войс уже публичный.", ephemeral=True)

        try:
            voice_channel: discord.VoiceChannel = interaction.channel
            overwrites = voice_channel.overwrites
            overwrites[interaction.guild.default_role] = discord.PermissionOverwrite(view_channel=True, connect=True)

            await voice_channel.edit(overwrites=overwrites)
            channel_is_private[voice_channel.id] = False
            self.is_private = False

            await interaction.response.send_message("Войс сделан публичным.", ephemeral=True)
        except Exception:
            await interaction.response.send_message("Не удалось сделать войс публичным.", ephemeral=True)

    @ui.button(label="Пригласить друзей", style=discord.ButtonStyle.green, custom_id="tempvoice_invite", row=2)
    async def invite_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Только создатель войса может приглашать.", ephemeral=True)

        if not isinstance(interaction.channel, discord.VoiceChannel):
            return await interaction.response.send_message("Это не голосовой канал.", ephemeral=True)

        try:
            invite = await interaction.channel.create_invite(max_age=3600, max_uses=10, reason=f"Приглашение от {interaction.user}")
            await interaction.response.send_message(f"Приглашение в войс готово!\n{invite.url}", ephemeral=True)
        except Exception:
            await interaction.response.send_message("Не удалось создать приглашение.", ephemeral=True)

    @ui.button(label="Выгнать участника", style=discord.ButtonStyle.red, custom_id="tempvoice_kick", row=2)
    async def kick_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Только создатель войса может выгонять участников.", ephemeral=True)

        voice_channel: discord.VoiceChannel = interaction.channel
        if not isinstance(voice_channel, discord.VoiceChannel):
            return await interaction.response.send_message("Ошибка канала.", ephemeral=True)

        members = [m for m in voice_channel.members if m.id != self.owner_id]
        if not members:
            return await interaction.response.send_message("В войсе нет других участников.", ephemeral=True)

        options = [
            discord.SelectOption(label=m.display_name[:25], value=str(m.id), description=f"{m.name}")
            for m in members
        ]

        class KickSelect(ui.Select):
            def __init__(self):
                super().__init__(placeholder="Выбери участника для изгнания...", min_values=1, max_values=1, options=options)

            async def callback(self, select_inter: discord.Interaction):
                if select_inter.user.id != interaction.user.id:
                    return await select_inter.response.send_message("Только владелец может использовать это меню.", ephemeral=True)

                target_id = int(self.values[0])
                member_to_kick = interaction.guild.get_member(target_id)

                if member_to_kick and member_to_kick in voice_channel.members:
                    try:
                        await member_to_kick.move_to(None, reason=f"Выгнан владельцем войса {interaction.user}")
                        await select_inter.response.send_message(f"{member_to_kick.mention} был выгнан из войса.", ephemeral=True)
                    except:
                        await select_inter.response.send_message("Не удалось выгнать участника.", ephemeral=True)
                else:
                    await select_inter.response.send_message("Участник уже покинул войс.", ephemeral=True)

        view = ui.View()
        view.add_item(KickSelect())
        await interaction.response.send_message("Выбери, кого выгнать:", view=view, ephemeral=True)


# ======================== АВТО-ТИКЕТЫ И ФИЛЬТР ========================

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    special_channels = {SCREENSHOTS_CHANNEL_ID, IRL_CHANNEL_ID}
    
    if message.channel.id in special_channels:
        has_attachment = any(att.content_type and att.content_type.startswith("image/") for att in message.attachments)

        if not has_attachment:
            try:
                await message.delete()
            except:
                pass
            await bot.process_commands(message)
            return

        try:
            thread_name = f"Обсуждение от {message.author.display_name}"
            thread = await message.create_thread(name=thread_name[:100], auto_archive_duration=1440)
            await thread.remove_user(message.author)
        except Exception as e:
            print(f"Не удалось создать ветку: {e}")

    if message.channel.id == SPAM_PROTECTION_CHANNEL_ID:
        try:
            after_time = datetime.utcnow() - timedelta(minutes=10)
            deleted_count = 0
            for channel in message.guild.text_channels:
                try:
                    async for msg in channel.history(limit=100, after=after_time):
                        if msg.author.id == message.author.id:
                            await msg.delete()
                            deleted_count += 1
                except:
                    continue

            reason = "Спам в канале спам-защиты. Автоматический бан на 7 дней."

            await message.guild.ban(message.author, reason=reason, delete_message_days=0)

            log_channel = message.guild.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                embed = discord.Embed(
                    title="Анти-спам: Пользователь забанен",
                    description="Автоматический бан за сообщение в канале спам-защиты",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
                embed.add_field(name="Пользователь", value=f"{message.author} ({message.author.id})", inline=False)
                embed.add_field(name="Причина", value=reason, inline=False)
                embed.add_field(name="Удалено сообщений (за 10 мин)", value=str(deleted_count), inline=False)
                embed.add_field(name="Длительность бана", value="7 дней", inline=False)
                await log_channel.send(embed=embed)

            try:
                await message.channel.send(f"{message.author.mention} был забанен на 7 дней за спам.", delete_after=10)
            except:
                pass
        except Exception as e:
            print(f"Ошибка анти-спам системы: {e}")

    await bot.process_commands(message)


# ======================== SETUP ========================

@bot.command(name="setup")
@commands.has_permissions(administrator=True)
async def setup(ctx):
    apply_channel = bot.get_channel(APPLY_CHANNEL_ID)
    if apply_channel:
        await apply_channel.purge(limit=10)
        embed = discord.Embed(
            title="Привет! Здесь ты можешь оставить заявку на сервер",
            description="Нажми кнопку ниже, чтобы подать заявку и присоединениться к AmberLand!",
            color=discord.Color(0xffbf00)
        )
        await apply_channel.send(embed=embed, view=ApplyView())

    support_channel = bot.get_channel(SUPPORT_CHANNEL_ID)
    if support_channel:
        await support_channel.purge(limit=10)
        embed = discord.Embed(
            title="Поддержка сервера AmberLand",
            description="Если у тебя возникла проблема — нажми кнопку ниже.",
            color=discord.Color(0xffbf00)
        )
        await support_channel.send(embed=embed, view=SupportApplyView())

    spam_channel = bot.get_channel(SPAM_PROTECTION_CHANNEL_ID)
    if spam_channel:
        await spam_channel.purge(limit=5)
        embed = discord.Embed(
            title="НЕ ПИШИТЕ В ЭТОМ КАНАЛЕ",
            description="Этот канал создан для защиты сервера от рекламы и сообщений от взломанных аккаунтов.",
            color=discord.Color.red()
        )
        embed.add_field(name="Важное правило:", value="Любое сообщение в этом канале = автоматический бан на 7 дней.", inline=False)
        await spam_channel.send(embed=embed)


# ======================== ЗАПУСК ========================

@bot.event
async def on_ready():
    print(f"Бот успешно запущен как {bot.user}")

    bot.add_view(ApplyView())
    bot.add_view(SupportApplyView())
    bot.add_view(TicketView(0, ""))
    bot.add_view(SupportTicketView(0, "", 0))
    bot.add_view(TempVoiceView(0, False))

    if not update_stats.is_running():
        update_stats.start()

    try:
        await bot.tree.sync()
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")


if __name__ == "__main__":
    bot.run(TOKEN)