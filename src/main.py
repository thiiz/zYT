import discord
from discord.ext import commands
import yt_dlp
import asyncio

# Configure yt-dlp options
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'prefer_ffmpeg': True,
    'keepvideo': False,
}

# Configure FFmpeg options
FFMPEG_OPTIONS = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

# Initialize bot with required intents
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

class MusicBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)
        self.ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)
        
    async def setup_hook(self):
        await self.add_cog(Music(self))

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = {}  # Dictionary to store music queues for different servers
        
    async def ensure_voice_state(self, ctx):
        """Check voice state and return voice client"""
        if ctx.author.voice is None:
            await ctx.send("You need to be in a voice channel to use this command.")
            return None
            
        voice_channel = ctx.author.voice.channel
        voice_client = ctx.voice_client
        
        if voice_client:
            if voice_client.channel != voice_channel:
                await voice_client.move_to(voice_channel)
        else:
            voice_client = await voice_channel.connect()
            
        return voice_client

    async def get_audio_url(self, query):
        """Extract audio URL from query"""
        try:
            print(f"Searching for: {query}")
            
            if not 'http' in query:
                query = f'ytsearch:{query}'
            
            try:
                # Extract info with detailed error handling
                data = await self.bot.loop.run_in_executor(
                    None, 
                    lambda: self.bot.ytdl.extract_info(query, download=False)
                )
            except yt_dlp.utils.DownloadError as e:
                print(f"yt-dlp download error: {e}")
                return None
            except Exception as e:
                print(f"Error during info extraction: {e}")
                return None
            
            # Handle search results
            if 'entries' in data:
                if not data['entries']:
                    print("No search results found")
                    return None
                data = data['entries'][0]
            
            # Get best audio format
            formats = data.get('formats', [])
            audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
            
            if audio_formats:
                # Select best audio format
                best_audio = max(audio_formats, key=lambda f: f.get('abr', 0) if f.get('abr') else 0)
                url = best_audio.get('url')
            else:
                # Fallback to best format available
                url = data.get('url')
            
            if not url or not data.get('title'):
                print("Missing required data in response")
                return None
                
            print(f"Successfully found: {data['title']}")
            return {
                'url': url,
                'title': data['title']
            }
        except Exception as e:
            print(f"Error extracting audio: {e}")
            return None

    @commands.command()
    async def play(self, ctx, *, query: str):
        """Play music from YouTube"""
        try:
            voice_client = await self.ensure_voice_state(ctx)
            if not voice_client:
                return

            async with ctx.typing():
                audio_data = await self.get_audio_url(query)
                if not audio_data:
                    await ctx.send("❌ Could not find the requested song. Please try again with a different search term or URL.")
                    return

                if voice_client.is_playing():
                    voice_client.stop()

                audio_source = discord.FFmpegPCMAudio(
                    audio_data['url'],
                    executable="C:/ffmpeg/bin/ffmpeg.exe",  # adjust this path
                    **FFMPEG_OPTIONS
                )
                voice_client.play(
                    discord.PCMVolumeTransformer(audio_source, volume=0.3), 
                    after=lambda e: print(f'Player error: {e}') if e else None
                )

            await ctx.send(f"🎵 Now playing: **{audio_data['title']}**")
            
        except Exception as e:
            print(f"Error in play command: {e}")
            await ctx.send(f"❌ An error occurred while trying to play the song. Please try again.")

    @commands.command()
    async def stop(self, ctx):
        """Stop the currently playing music"""
        voice_client = ctx.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.stop()
            await ctx.send("⏹️ Music stopped.")
        else:
            await ctx.send("No music is currently playing.")
            
    @commands.command()
    async def pause(self, ctx):
        """Pause the currently playing music"""
        voice_client = ctx.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.pause()
            await ctx.send("⏸️ Music paused.")
        else:
            await ctx.send("No music is currently playing.")

    @commands.command()
    async def resume(self, ctx):
        """Resume the paused music"""
        voice_client = ctx.voice_client
        if voice_client and voice_client.is_paused():
            voice_client.resume()
            await ctx.send("▶️ Music resumed.")
        else:
            await ctx.send("No music is currently paused.")

    
    @commands.command()
    async def volume(self, ctx, volume: int):
        voice_client = ctx.voice_client
        if voice_client and voice_client.source:
            voice_client.source.volume = volume / 100  # Convertendo de 0-100 para 0.0-1.0
            await ctx.send(f"🔊 Volume ajustado para {volume}%")
        else:
            await ctx.send("❌ Não estou tocando nenhuma música no momento.")

    @commands.command()
    async def leave(self, ctx):
        """Disconnect the bot from voice channel"""
        voice_client = ctx.voice_client
        if voice_client:
            await voice_client.disconnect()
            await ctx.send("👋 Goodbye!")
        else:
            await ctx.send("I'm not connected to any voice channel.")

    @play.error
    async def play_error(self, ctx, error):
        """Error handler for the play command"""
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("❌ Please specify a song to play. Usage: !play <song name or URL>")
        else:
            print(f"Unexpected error in play command: {error}")
            await ctx.send("❌ An unexpected error occurred. Please try again.")

# Create and run the bot
bot = MusicBot()

@bot.event
async def on_ready():
    print(f'Bot is ready as {bot.user.name}')
    print('------')

# Run the bot
bot.run('discord_token')