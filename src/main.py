# import os
# os.system('apt-get update')
# os.system('apt-get install -y ffmpeg')
# os.system('pip install discord.py')
# os.system('pip install yt_dlp')
# os.system('pip install -U discord.py[voice]')
import discord
from discord.ext import commands
import yt_dlp
import asyncio
from typing import Optional, Dict, List
import re

DISCORD_TOKEN="TOKEN"
DEFAULT_VOLUME = 0.3

YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'prefer_ffmpeg': True,
    'keepvideo': False,
    'extract_flat': 'in_playlist',
    'playliststart': 1,
    'playlistend': 50,
    'cookiefile': './cookies.txt',
}

FFMPEG_OPTIONS = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

class Track:
    def __init__(self, video_id: str, title: str, duration: int, thumbnail: str):
        self.video_id = video_id
        self.title = title
        self.duration = duration
        self.thumbnail = thumbnail
        self.url = f"https://youtube.com/watch?v={video_id}"

    @staticmethod
    def format_duration(seconds: float) -> str:
        seconds = int(seconds)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    def __str__(self) -> str:
        return f"[{self.title}]({self.url}) ({self.format_duration(self.duration)})"

class GuildQueue:
    def __init__(self):
        self.tracks: List[Track] = []
        self.current_track: Optional[Track] = None
        self.loop: bool = False
        self.text_channel = None
        self.volume: float = DEFAULT_VOLUME  # Volume padrão (30%)

class MusicBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        super().__init__(command_prefix='!', intents=intents)
        self.ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)
        
    async def setup_hook(self):
        await self.add_cog(Music(self))

class Music(commands.Cog):
    def __init__(self, bot: MusicBot):
        self.bot = bot
        self.guild_queues: Dict[int, GuildQueue] = {}
        
    def get_queue(self, guild_id: int) -> GuildQueue:
        if guild_id not in self.guild_queues:
            self.guild_queues[guild_id] = GuildQueue()
        return self.guild_queues[guild_id]

    async def ensure_voice_state(self, ctx: commands.Context) -> Optional[discord.VoiceClient]:
        if ctx.author.voice is None:
            embed = discord.Embed(
                title="❌ Erro de Conexão",
                description="Você precisa estar em um canal de voz para usar este comando.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed, silent=True)
            return None
            
        voice_channel = ctx.author.voice.channel
        voice_client = ctx.voice_client
        
        if voice_client:
            if voice_client.channel != voice_channel:
                await voice_client.move_to(voice_channel)
        else:
            voice_client = await voice_channel.connect()
            
        return voice_client

    def extract_track_info(self, data: dict) -> Optional[Track]:
        try:
            video_id = data.get('id')
            if not video_id:
                return None

            title = data.get('title', 'Unknown Title')
            duration = data.get('duration', 0)
            thumbnail = data.get('thumbnail', '')

            return Track(
                video_id=video_id,
                title=title,
                duration=duration,
                thumbnail=thumbnail
            )
        except Exception as e:
            print(f"Erro ao extrair informações da faixa: {e}")
            return None

    async def play_next(self, guild: discord.Guild):
        queue = self.get_queue(guild.id)
        voice_client = guild.voice_client

        if not voice_client or not voice_client.is_connected():
            return

        if queue.loop and queue.current_track:
            queue.tracks.append(queue.current_track)

        if not queue.tracks:
            queue.current_track = None
            return

        track = queue.tracks.pop(0)
        queue.current_track = track

        if queue.text_channel:
            embed = discord.Embed(
                title="🎵 Começando a Tocar",
                description=f"[{track.title}]({track.url})\n⏱️ Duração: {Track.format_duration(track.duration)}",
                color=discord.Color.blue()
            )
            if track.thumbnail:
                embed.set_thumbnail(url=track.thumbnail)
            await queue.text_channel.send(embed=embed, silent=True)

        video_url = f"https://youtube.com/watch?v={track.video_id}"
        try:
            data = await self.bot.loop.run_in_executor(
                None, 
                lambda: self.bot.ytdl.extract_info(video_url, download=False)
            )
            if not data:
                embed = discord.Embed(
                    title="❌ Erro de Reprodução",
                    description=f"Não foi possível obter informações para [{track.title}]({track.url})",
                    color=discord.Color.red()
                )
                await queue.text_channel.send(embed=embed, silent=True)
                queue.current_track = None
                return

            formats = data.get('formats', [])
            audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
            if audio_formats:
                best_audio = max(audio_formats, key=lambda f: f.get('abr', 0) if f.get('abr') else 0)
                url = best_audio.get('url')
            else:
                url = data.get('url')

            if not url:
                embed = discord.Embed(
                    title="❌ Erro de Reprodução",
                    description=f"Nenhuma URL reproduzível encontrada para [{track.title}]({track.url})",
                    color=discord.Color.red()
                )
                await queue.text_channel.send(embed=embed, silent=True)
                queue.current_track = None
                return

            audio_source = discord.FFmpegPCMAudio(
                url,
                executable="ffmpeg",
                **FFMPEG_OPTIONS
            )
            source = discord.PCMVolumeTransformer(audio_source, volume=queue.volume)

            def after_playing(error):
                if error:
                    print(f'Erro no player (ignorado): {error}')
                asyncio.run_coroutine_threadsafe(self.play_next(guild), self.bot.loop)

            voice_client.play(source, after=after_playing)

        except Exception as e:
            embed = discord.Embed(
                title="❌ Erro de Reprodução",
                description=f"Erro ao reproduzir [{track.title}]({track.url})\n```{str(e)}```",
                color=discord.Color.red()
            )
            await queue.text_channel.send(embed=embed, silent=True)
            queue.current_track = None

    @commands.command(name="p", aliases=["play"])
    async def play(self, ctx: commands.Context, *, query: str):
        voice_client = await self.ensure_voice_state(ctx)
        if not voice_client:
            return

        queue = self.get_queue(ctx.guild.id)
        queue.text_channel = ctx.channel

        async with ctx.typing():
            is_url = bool(re.match(r'https?://(?:www\.)?.+', query))
            processed_query = query if is_url else f'ytsearch:{query}'

            try:
                data = await self.bot.loop.run_in_executor(
                    None, 
                    lambda: self.bot.ytdl.extract_info(processed_query, download=False)
                )

                if not data:
                    embed = discord.Embed(
                        title="❌ Erro na Busca",
                        description="Não foi possível encontrar a música solicitada.",
                        color=discord.Color.red()
                    )
                    await ctx.send(embed=embed, silent=True)
                    return

                # Se for playlist
                if data.get('_type') == 'playlist':
                    tracks = []
                    entries = data.get('entries', [])
                    for entry in entries:
                        if entry:
                            track = self.extract_track_info(entry)
                            if track:
                                tracks.append(track)
                    
                    if tracks:
                        queue.tracks.extend(tracks)
                        embed = discord.Embed(
                            title="📑 Playlist Adicionada",
                            description=f"✅ **{len(tracks)} músicas** adicionadas à fila\n\n🎵 **Primeira música:**\n[{tracks[0].title}]({tracks[0].url})\n⏱️ Duração: {Track.format_duration(tracks[0].duration)}",
                            color=discord.Color.green()
                        )
                        if tracks[0].thumbnail:
                            embed.set_thumbnail(url=tracks[0].thumbnail)
                        embed.set_footer(text=f"Use !q para ver a fila completa | Total na fila: {len(queue.tracks)}")
                        await ctx.send(embed=embed, silent=True)

                else:
                    track = self.extract_track_info(data)
                    if track:
                        queue.tracks.append(track)
                        position = len(queue.tracks)
                        
                        embed = discord.Embed(
                            title="🎵 Música Adicionada",
                            description=f"✅ Adicionada à fila:\n[{track.title}]({track.url})\n\n⏱️ Duração: {Track.format_duration(track.duration)}\n📍 Posição na fila: {position}",
                            color=discord.Color.green()
                        )
                        if track.thumbnail:
                            embed.set_thumbnail(url=track.thumbnail)
                        embed.set_footer(text="Use !q para ver a fila completa")
                        await ctx.send(embed=embed, silent=True)

            except Exception as e:
                embed = discord.Embed(
                    title="❌ Erro",
                    description=f"Ocorreu um erro ao processar sua solicitação:\n```{str(e)}```",
                    color=discord.Color.red()
                )
                await ctx.send(embed=embed, silent=True)
                return

        if not voice_client.is_playing() and not voice_client.is_paused():
            await self.play_next(ctx.guild)

    @commands.command(name="q", aliases=["queue"])
    async def show_queue(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        
        if not queue.current_track and not queue.tracks:
            embed = discord.Embed(
                title="📭 Fila Vazia",
                description="Nenhuma música na fila. Use !play para adicionar músicas!",
                color=discord.Color.light_grey()
            )
            await ctx.send(embed=embed, silent=True)
            return

        embed = discord.Embed(
            title="🎶 Fila de Reprodução",
            color=discord.Color.blue()
        )

        if queue.current_track:
            embed.add_field(
                name="🔊 Tocando Agora",
                value=f"[{queue.current_track.title}]({queue.current_track.url})\n⏱️ {Track.format_duration(queue.current_track.duration)}",
                inline=False
            )

        if queue.tracks:
            track_list = []
            for i, track in enumerate(queue.tracks[:10], 1):
                track_list.append(
                    f"`{i}.` [{track.title}]({track.url})\n⏱️ {Track.format_duration(track.duration)}"
                )
            
            remaining = len(queue.tracks) - 10 if len(queue.tracks) > 10 else 0
            
            tracks_text = "\n\n".join(track_list)
            if remaining > 0:
                tracks_text += f"\n\n*...e mais {remaining} músicas na fila*"
            
            embed.add_field(
                name="📋 Próximas Músicas",
                value=tracks_text,
                inline=False
            )

        total_duration = sum(track.duration for track in queue.tracks)
        if queue.current_track:
            total_duration += queue.current_track.duration

        status = []
        status.append(f"🔄 Loop: {'Ativado' if queue.loop else 'Desativado'}")
        status.append(f"🔊 Volume: {int(queue.volume * 100)}%")
        status.append(f"⏱️ Tempo total: {Track.format_duration(total_duration)}")
        
        embed.set_footer(text=" | ".join(status))
        await ctx.send(embed=embed, silent=True)

    @commands.command(name="loop")
    async def toggle_loop(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        queue.loop = not queue.loop
        
        embed = discord.Embed(
            title="🔄 Modo Loop",
            description=f"Loop {'ativado' if queue.loop else 'desativado'} com sucesso!",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed, silent=True)

    @commands.command(name="clear")
    async def clear_queue(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        old_length = len(queue.tracks)
        queue.tracks.clear()
        
        embed = discord.Embed(
            title="🗑️ Fila Limpa",
            description=f"Foram removidas {old_length} músicas da fila",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed, silent=True)

    @commands.command(name="s", aliases=["skip"])
    async def skip(self, ctx: commands.Context):
        voice_client = ctx.voice_client
        if voice_client and voice_client.is_playing():
            current_track = self.get_queue(ctx.guild.id).current_track
            voice_client.stop()
            
            embed = discord.Embed(
                title="⏭️ Música Pulada",
                description=f"Pulando [{current_track.title}]({current_track.url})",
                color=discord.Color.blue()
            )
            await ctx.send(embed=embed, silent=True)
        else:
            embed = discord.Embed(
                title="❌ Erro ao Pular",
                description="Não há nenhuma música tocando no momento",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed, silent=True)

    @commands.command()
    async def pause(self, ctx: commands.Context):
        voice_client = ctx.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.pause()
            current_track = self.get_queue(ctx.guild.id).current_track
            
            embed = discord.Embed(
                title="⏸️ Música Pausada",
                description=f"[{current_track.title}]({current_track.url}) foi pausada",
                color=discord.Color.blue()
            )
            await ctx.send(embed=embed, silent=True)
        else:
            embed = discord.Embed(
                title="❌ Erro ao Pausar",
                description="Não há nenhuma música tocando no momento",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed, silent=True)

    @commands.command()
    async def resume(self, ctx: commands.Context):
        voice_client = ctx.voice_client
        if voice_client and voice_client.is_paused():
            voice_client.resume()
            current_track = self.get_queue(ctx.guild.id).current_track
            
            embed = discord.Embed(
                title="▶️ Música Retomada",
                description=f"[{current_track.title}]({current_track.url}) foi retomada",
                color=discord.Color.blue()
            )
            await ctx.send(embed=embed, silent=True)
        else:
            embed = discord.Embed(
                title="❌ Erro ao Retomar",
                description="Não há nenhuma música pausada no momento",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed, silent=True)

    @commands.command()
    async def volume(self, ctx: commands.Context, volume: int):
        """Define o volume (0-100)"""
        if not 0 <= volume <= 100:
            embed = discord.Embed(
                title="❌ Erro no Volume",
                description="O volume deve estar entre 0 e 100",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed, silent=True)
            return

        queue = self.get_queue(ctx.guild.id)
        old_volume = int(queue.volume * 100)
        queue.volume = volume / 100

        voice_client = ctx.voice_client
        if voice_client and voice_client.source:
            voice_client.source.volume = queue.volume
            embed = discord.Embed(
                title="🔊 Volume Ajustado",
                description=f"Volume alterado: **{old_volume}%** → **{volume}%**",
                color=discord.Color.blue()
            )
        else:
            embed = discord.Embed(
                title="🔊 Volume Configurado",
                description=f"Volume será **{volume}%** na próxima música",
                color=discord.Color.blue()
            )
        
        await ctx.send(embed=embed, silent=True)

    @commands.command()
    async def leave(self, ctx: commands.Context):
        voice_client = ctx.voice_client
        if voice_client:
            queue = self.get_queue(ctx.guild.id)
            tracks_count = len(queue.tracks)
            
            if ctx.guild.id in self.guild_queues:
                del self.guild_queues[ctx.guild.id]
            
            await voice_client.disconnect()
            
            embed = discord.Embed(
                title="👋 Desconectado",
                description=f"Saí do canal de voz e limpei a fila com {tracks_count} músicas",
                color=discord.Color.blue()
            )
            await ctx.send(embed=embed, silent=True)
        else:
            embed = discord.Embed(
                title="❌ Erro ao Sair",
                description="Não estou em nenhum canal de voz",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)

    @commands.command(name="np", aliases=["now", "playing"])
    async def now_playing(self, ctx: commands.Context):
        """Mostra informações sobre a música atual"""
        queue = self.get_queue(ctx.guild.id)
        
        if not queue.current_track:
            embed = discord.Embed(
                title="❌ Nada Tocando",
                description="Não há nenhuma música tocando no momento",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed, silent=True)
            return
            
        embed = discord.Embed(
            title="🎵 Tocando Agora",
            description=f"[{queue.current_track.title}]({queue.current_track.url})\n⏱️ Duração: {Track.format_duration(queue.current_track.duration)}",
            color=discord.Color.blue()
        )
        
        if queue.current_track.thumbnail:
            embed.set_thumbnail(url=queue.current_track.thumbnail)
            
        status = []
        status.append(f"🔄 Loop: {'Ativado' if queue.loop else 'Desativado'}")
        status.append(f"🔊 Volume: {int(queue.volume * 100)}%")
        
        embed.set_footer(text=" | ".join(status))
        await ctx.send(embed=embed, silent=True)

bot = MusicBot()
bot.remove_command("help")

@bot.event
async def on_ready():
    print(f'Bot está pronto como {bot.user.name}')
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening,
        name="!play | !help"
    ))
    print('------')

@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(
        title="📜 Lista de Comandos",
        description="Aqui estão todos os comandos disponíveis:",
        color=discord.Color.blue()
    )
    
    commands_list = {
        "🎵 Música": {
            "!p ou !play": "Toca uma música ou playlist (!p <nome ou URL>)",
            "!s ou !skip": "Pula a música atual",
            "!q ou !queue": "Mostra a fila de reprodução",
            "!np": "Mostra a música atual",
            "!pause": "Pausa a música",
            "!resume": "Retoma a música pausada",
            "!loop": "Ativa/desativa o modo loop",
            "!clear": "Limpa a fila de reprodução"
        },
        "⚙️ Configurações": {
            "!volume": "Ajusta o volume (0-100)",
            "!leave": "Desconecta o bot do canal"
        }
    }
    
    for category, cmds in commands_list.items():
        command_text = "\n".join(f"`{cmd}`: {desc}" for cmd, desc in cmds.items())
        embed.add_field(name=category, value=command_text, inline=False)
        
    embed.set_footer(text="🎵 Divirta-se com a música!")
    await ctx.send(embed=embed, silent=True)

bot.run(DISCORD_TOKEN)
