"""Australis announcement editor and configurable Workshop link."""
import logging
import re
from urllib.parse import urlsplit, parse_qs

import discord
from discord import app_commands


def collection_url(value):
    url = urlsplit(value.strip())
    ids = parse_qs(url.query).get('id', [])
    if (url.scheme != 'https' or url.netloc != 'steamcommunity.com'
            or url.path.rstrip('/') not in ('/sharedfiles/filedetails', '/workshop/filedetails')
            or len(ids) != 1 or not re.fullmatch(r'[1-9][0-9]{0,19}', ids[0])):
        raise ValueError('Нужна ссылка https://steamcommunity.com/sharedfiles/filedetails/?id=123456789')
    return 'https://steamcommunity.com/sharedfiles/filedetails/?id=' + ids[0]


def image_url(value):
    if not value.strip():
        return None
    url = urlsplit(value.strip())
    if url.scheme != 'https' or not url.hostname or url.username or len(value) > 1000:
        raise ValueError('Для изображения нужна прямая HTTPS-ссылка длиной до 1000 символов.')
    return value.strip()


def install(bot, store, card):
    class Editor(discord.ui.Modal):
        def __init__(self, owner, channel, message=None):
            super().__init__(title='Панель Australis Project', timeout=600)
            self.owner, self.channel, self.message = owner, channel, message
            old = message.embeds[0] if message and message.embeds else None
            self.heading = discord.ui.TextInput(label='Заголовок', max_length=200, default=old.title if old else None)
            self.body = discord.ui.TextInput(label='Текст панели — Markdown и переносы строк', style=discord.TextStyle.paragraph, max_length=3500, default=old.description if old else None)
            self.picture = discord.ui.TextInput(label='Прямая HTTPS-ссылка на картинку', required=False, max_length=1000, default=old.image.url if old and old.image else None)
            for field in (self.heading, self.body, self.picture): self.add_item(field)

        async def on_submit(self, i):
            if i.user.id != self.owner or not i.user.guild_permissions.manage_guild:
                await i.response.send_message('Нужно право «Управлять сервером».', ephemeral=True); return
            p = self.channel.permissions_for(i.user)
            bp = self.channel.permissions_for(i.guild.me)
            if not (p.view_channel and p.send_messages and bp.view_channel and bp.send_messages and bp.embed_links):
                await i.response.send_message('Проверь доступ к каналу и право бота «Встраивать ссылки».', ephemeral=True); return
            try:
                picture = image_url(str(self.picture))
                title, body = str(self.heading).strip(), str(self.body).strip()
                if not title or not body: raise ValueError('Заполни заголовок и текст.')
            except ValueError as e:
                await i.response.send_message(str(e), ephemeral=True); return
            await i.response.defer(ephemeral=True)
            embed = card(title, body)
            if picture: embed.set_image(url=picture)
            if self.message:
                message = await self.message.edit(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            else:
                message = await self.channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                with store.edit(i.guild_id) as s:
                    s.setdefault('custom_panels', {})[str(message.id)] = self.channel.id
            await i.followup.send(f'Панель сохранена: {message.jump_url}', ephemeral=True)

        async def on_error(self, i, error):
            logging.error('Panel editor failed', exc_info=(type(error), error, error.__traceback__))
            text = 'Не удалось сохранить панель. Проверь права бота и наличие сообщения.'
            if i.response.is_done(): await i.followup.send(text, ephemeral=True)
            else: await i.response.send_message(text, ephemeral=True)

    @bot.tree.command(name='post', description='Создать панель с твоим текстом и картинкой в выбранном канале')
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def post(i: discord.Interaction, channel: discord.TextChannel):
        await i.response.send_modal(Editor(i.user.id, channel))

    @bot.tree.command(name='post_edit', description='Изменить ранее созданную через /post панель по ID сообщения')
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def post_edit(i: discord.Interaction, message_id: str):
        with store.edit(i.guild_id) as s: cid = s.get('custom_panels', {}).get(message_id)
        channel = i.guild.get_channel(cid) if cid else None
        if not channel or not channel.permissions_for(i.user).view_channel:
            await i.response.send_message('Панель не найдена. Укажи ID сообщения, созданного через /post на этом сервере.', ephemeral=True); return
        # Fetch before the modal; modal responses cannot follow a deferred response.
        message = await channel.fetch_message(int(message_id))
        if message.author.id != bot.user.id:
            await i.response.send_message('Это не панель бота.', ephemeral=True); return
        await i.response.send_modal(Editor(i.user.id, channel, message))

    @bot.tree.command(name='collection_set', description='Сохранить ссылку на коллекцию аддонов Steam Workshop')
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def collection_set(i: discord.Interaction, url: str):
        try: url = collection_url(url)
        except ValueError as e:
            await i.response.send_message(str(e), ephemeral=True); return
        with store.edit(i.guild_id) as s: s['collection_url'] = url
        await i.response.send_message('Ссылка сохранена. Теперь участникам доступна /collection.', ephemeral=True)

    @bot.tree.command(name='collection', description='Коллекция аддонов Australis Project в Steam Workshop')
    @app_commands.guild_only()
    async def collection(i: discord.Interaction):
        with store.edit(i.guild_id) as s: url = s.get('collection_url')
        if not url:
            await i.response.send_message('Коллекция ещё не настроена. Администратор может задать её через /collection_set.', ephemeral=True); return
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label='Открыть коллекцию', url=url))
        await i.response.send_message(embed=card('КОЛЛЕКЦИЯ СЕРВЕРА', f'Аддоны для игры на **Australis Project**.\n\n[Перейти в Steam Workshop]({url})\nНажми «Подписаться на все» на странице коллекции.'), view=view)
