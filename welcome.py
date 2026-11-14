"""Configurable Discord join greetings, independent of invite tracking."""
import logging
import re
import discord
from discord import app_commands

DEFAULT = ('{member}, добро пожаловать в **Australis Project**!\n\n'
           'Альянс пал. История продолжается — и теперь ты её часть.\n'
           'Ознакомься с правилами и информацией о проекте.\n\n'
           'Коллекция аддонов: `/collection` • Игры: `/snake`')


def render(template, member):
    values = {
        'member': member.mention,
        'name': discord.utils.escape_markdown(member.display_name),
        'server': discord.utils.escape_markdown(member.guild.name),
        'count': str(member.guild.member_count or '—'),
    }
    # Single pass: braces in member/server names must remain literal.
    return re.sub(r'\{(member|name|server|count)\}', lambda m: values[m[1]], template)[:4096]


def channel_error(channel, guild):
    if channel is None:
        return 'Канал приветствий удалён или недоступен. Повтори /welcome_setup.'
    p = channel.permissions_for(guild.me)
    if not (p.view_channel and p.send_messages and p.embed_links):
        return 'Боту нужны права «Просматривать канал», «Отправлять сообщения» и «Встраивать ссылки».'
    return None


def greeting(member, template):
    embed = discord.Embed(title='ДОБРО ПОЖАЛОВАТЬ В AUSTRALIS',
                          description=render(template, member), color=0xb83232)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f'Australis Project • Участников: {member.guild.member_count or "—"}')
    return embed


def install(bot, store):
    async def send(channel, member, template):
        return await channel.send(
            content=member.mention, embed=greeting(member, template),
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=[member], replied_user=False))

    async def welcome_member(member):
        if member.bot:
            return
        with store.edit(member.guild.id) as state:
            cfg = dict(state.get('welcome', {}))
        if not cfg.get('enabled'):
            return
        channel = member.guild.get_channel(cfg['channel'])
        error = channel_error(channel, member.guild)
        if error:
            logging.warning('Welcome unavailable in guild %s: %s', member.guild.id, error)
            return
        try:
            await send(channel, member, cfg['text'])
        except discord.HTTPException:
            logging.exception('Could not send welcome in guild %s', member.guild.id)

    bot.add_listener(welcome_member, 'on_member_join')

    @bot.tree.command(name='welcome_setup', description='Включить приветствия новых участников в выбранном канале')
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(channel='Канал приветствий', text='Свой текст: {member}, {name}, {server}, {count}. Пусто — стандартный текст')
    async def setup(i: discord.Interaction, channel: discord.TextChannel, text: app_commands.Range[str, 1, 2500] | None = None):
        error = channel_error(channel, i.guild)
        if not channel.permissions_for(i.user).view_channel:
            error = 'У тебя нет доступа к этому каналу.'
        if text is not None and not text.strip():
            error = 'Текст не должен состоять только из пробелов.'
        with store.edit(i.guild_id) as state:
            if channel.id in [state['channels'].get(k) for k in ('count', 'words', 'wait')]:
                error = 'Выбери отдельный канал, не занятый текстовыми играми.'
        if error:
            await i.response.send_message(error, ephemeral=True); return
        template = text if text is not None else DEFAULT
        with store.edit(i.guild_id) as state:
            state['welcome'] = {'enabled': True, 'channel': channel.id, 'text': template}
        await i.response.send_message(f'Приветствия включены в {channel.mention}. Ниже пример для тебя. Публичная проверка: /welcome_test.', embed=greeting(i.user, template), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @bot.tree.command(name='welcome_test', description='Отправить тестовое приветствие для тебя в настроенный канал')
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def test(i: discord.Interaction):
        with store.edit(i.guild_id) as state: cfg = dict(state.get('welcome', {}))
        if not cfg.get('enabled'):
            await i.response.send_message('Сначала включи приветствия через /welcome_setup.', ephemeral=True); return
        channel = i.guild.get_channel(cfg['channel'])
        error = channel_error(channel, i.guild)
        if error:
            await i.response.send_message(error, ephemeral=True); return
        await i.response.defer(ephemeral=True)
        message = await send(channel, i.user, cfg['text'])
        await i.followup.send(f'Тестовое приветствие: {message.jump_url}', ephemeral=True)

    @bot.tree.command(name='welcome_off', description='Отключить автоматические приветствия')
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def off(i: discord.Interaction):
        with store.edit(i.guild_id) as state: state.setdefault('welcome', {})['enabled'] = False
        await i.response.send_message('Приветствия отключены. Включить снова: /welcome_setup.', ephemeral=True)
