import os
import sys
import asyncio
import json
import random
import time
import threading
import requests
from io import BytesIO
import discord
from discord.ext import commands

# ============================================================
# CONFIGURATION
# ============================================================

# Parse tokens from environment variable (comma-separated bot tokens)
TOKENS_ENV = os.environ.get("TOKENS", "")
if not TOKENS_ENV.strip():
    print("[FATAL] TOKENS environment variable is empty or not set!")
    print("[FATAL] Please set TOKENS in your Render environment variables.")
    print("[FATAL] Example: TOKENS=bot_token_1,bot_token_2,bot_token_3")
    sys.exit(1)

TOKENS = [t.strip() for t in TOKENS_ENV.split(",") if t.strip()]
print(f"[INFO] Loaded {len(TOKENS)} bot token(s) from environment.")

# Parse primary owners (comma-separated user IDs)
PRIMARY_OWNERS_ENV = os.environ.get("PRIMARY_OWNERS", "")
if not PRIMARY_OWNERS_ENV.strip():
    print("[FATAL] PRIMARY_OWNERS environment variable is empty or not set!")
    print("[FATAL] Please set PRIMARY_OWNERS in your Render environment variables.")
    print("[FATAL] Example: PRIMARY_OWNERS=123456789,987654321")
    sys.exit(1)

PRIMARY_OWNERS = [int(uid.strip()) for uid in PRIMARY_OWNERS_ENV.split(",") if uid.strip().isdigit()]
if not PRIMARY_OWNERS:
    print("[FATAL] PRIMARY_OWNERS contains no valid numeric user IDs!")
    sys.exit(1)
print(f"[INFO] Primary owners: {PRIMARY_OWNERS}")

# Parse allowed channels (optional, comma-separated channel IDs)
ALLOWED_CHANNELS_ENV = os.environ.get("ALLOWED_CHANNELS", "")
ALLOWED_CHANNELS = []
if ALLOWED_CHANNELS_ENV.strip():
    ALLOWED_CHANNELS = [int(cid.strip()) for cid in ALLOWED_CHANNELS_ENV.split(",") if cid.strip().isdigit()]
    print(f"[INFO] Allowed channels: {ALLOWED_CHANNELS}")
else:
    print("[INFO] No ALLOWED_CHANNELS set — bots will operate in ALL channels.")

# ============================================================
# GLOBAL STATE
# ============================================================

secondary_owners = {}  # bot_index -> set of user IDs
dm_spam_active = {}    # bot_index -> {"target_id": int, "message": str, "delay": float, "stop_flag": threading.Event()}
channel_spam_active = {}  # bot_index -> {"channel_id": int, "message": str, "delay": float, "stop_flag": threading.Event()}
fuckvc_active = {}     # bot_index -> {"guild_id": int, "vc_id": int, "stop_flag": threading.Event()}
muted_users = {}       # bot_index -> set of user IDs

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def is_allowed_channel(channel_id):
    """Check if a channel is in the allowed whitelist."""
    if not ALLOWED_CHANNELS:
        return True
    return channel_id in ALLOWED_CHANNELS

def is_primary_owner(user_id):
    return user_id in PRIMARY_OWNERS

def is_owner(bot_index, user_id):
    if user_id in PRIMARY_OWNERS:
        return True
    if bot_index in secondary_owners and user_id in secondary_owners[bot_index]:
        return True
    return False

def get_embed(title, description, color=discord.Color.blue()):
    embed = discord.Embed(title=title, description=description, color=color)
    return embed

# ============================================================
# BOT FACTORY
# ============================================================

def make_bot(token, bot_index):
    intents = discord.Intents.all()
    bot = commands.Bot(command_prefix="!", intents=intents)
    
    # Initialize state for this bot
    secondary_owners[bot_index] = set()
    dm_spam_active[bot_index] = None
    channel_spam_active[bot_index] = None
    fuckvc_active[bot_index] = None
    muted_users[bot_index] = set()

    # ============================================================
    # EVENTS
    # ============================================================

    @bot.event
    async def on_ready():
        print(f"[✓] Bot {bot_index} logged in as {bot.user} (ID: {bot.user.id})")
        # Set bot status
        await bot.change_presence(status=discord.Status.online)

    @bot.event
    async def on_message(message):
        # Ignore own messages to prevent loops
        if message.author.id == bot.user.id:
            return

        # Channel whitelist check
        if not is_allowed_channel(message.channel.id):
            return

        await bot.process_commands(message)

    # ============================================================
    # COMMANDS
    # ============================================================

    @bot.command(name="helpog")
    async def helpog(ctx):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_owner(bot_index, ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "You are not an owner of this bot.", discord.Color.red()))
            return

        help_text = """
**📨 DM Commands**
`!dmspam <user_id> <message>` — Start DM spam
`!dmspamstop` — Stop DM spam

**💬 Channel Commands**
`!spam <channel_id> <message>` — Start channel spam
`!stopspam` — Stop channel spam

**🔊 Voice Commands**
`!fuckvc <vc_id>` — Fuck up a voice channel
`!fuckvcstop` — Stop fucking VC

**🛡️ Moderation**
`!delete <amount>` — Delete messages
`!ban <user_id>` — Ban a user
`!kick <user_id>` — Kick a user
`!mute <user_id>` — Mute a user

**👤 Profile**
`!updatepfp <image_url>` — Update profile picture
`!updatebio <text>` — Update bio
`!updatelis <text>` — Update "Listening to" status

**👑 Owner Management (Primary only)**
`!ownset <user_id>` — Add secondary owner
`!ownremove <user_id>` — Remove secondary owner
`!listowns` — List all owners
        """.strip()
        await ctx.send(embed=get_embed("📚 **Help Menu**", help_text, discord.Color.green()))

    @bot.command(name="dmspam")
    async def dmspam(ctx, target_id: int, *, message: str):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_owner(bot_index, ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "You are not an owner.", discord.Color.red()))
            return

        delay = 1.0
        parts = message.rsplit(" |delay=", 1)
        if len(parts) > 1:
            message = parts[0]
            try:
                delay = float(parts[1])
            except:
                pass

        stop_flag = threading.Event()
        dm_spam_active[bot_index] = {
            "target_id": target_id,
            "message": message,
            "delay": delay,
            "stop_flag": stop_flag
        }

        await ctx.send(embed=get_embed("✅ **DM Spam Started**", f"Target: `{target_id}`\nDelay: `{delay}s`\nMessage: `{message[:50]}...`", discord.Color.green()))

        async def spam_loop():
            user = await bot.fetch_user(target_id)
            while not stop_flag.is_set():
                try:
                    await user.send(message)
                except discord.Forbidden:
                    await ctx.send(embed=get_embed("⚠️ DM Error", "Cannot DM this user (DMs closed or blocked).", discord.Color.orange()))
                    break
                except Exception as e:
                    await ctx.send(embed=get_embed("⚠️ DM Error", f"Failed to send DM: {str(e)}", discord.Color.orange()))
                    break
                stop_flag.wait(delay)

        asyncio.ensure_future(spam_loop())

    @bot.command(name="dmspamstop")
    async def dmspamstop(ctx):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_owner(bot_index, ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "You are not an owner.", discord.Color.red()))
            return
        if dm_spam_active[bot_index] is None:
            await ctx.send(embed=get_embed("⚠️ No Active Spam", "No DM spam is currently running.", discord.Color.orange()))
            return
        dm_spam_active[bot_index]["stop_flag"].set()
        dm_spam_active[bot_index] = None
        await ctx.send(embed=get_embed("🛑 **DM Spam Stopped**", "All DM spam has been stopped.", discord.Color.red()))

    @bot.command(name="spam")
    async def spam(ctx, channel_id: int, *, message: str):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_owner(bot_index, ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "You are not an owner.", discord.Color.red()))
            return

        delay = 1.0
        parts = message.rsplit(" |delay=", 1)
        if len(parts) > 1:
            message = parts[0]
            try:
                delay = float(parts[1])
            except:
                pass

        stop_flag = threading.Event()
        channel_spam_active[bot_index] = {
            "channel_id": channel_id,
            "message": message,
            "delay": delay,
            "stop_flag": stop_flag
        }

        await ctx.send(embed=get_embed("✅ **Channel Spam Started**", f"Channel: `{channel_id}`\nDelay: `{delay}s`\nMessage: `{message[:50]}...`", discord.Color.green()))

        async def spam_loop():
            channel = bot.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await bot.fetch_channel(channel_id)
                except:
                    await ctx.send(embed=get_embed("❌ Error", "Could not find channel.", discord.Color.red()))
                    return
            while not stop_flag.is_set():
                try:
                    await channel.send(message)
                except discord.Forbidden:
                    await ctx.send(embed=get_embed("⚠️ Channel Error", "Missing permissions to send messages in that channel.", discord.Color.orange()))
                    break
                except Exception as e:
                    await ctx.send(embed=get_embed("⚠️ Channel Error", f"Failed to send: {str(e)}", discord.Color.orange()))
                    break
                stop_flag.wait(delay)

        asyncio.ensure_future(spam_loop())

    @bot.command(name="stopspam")
    async def stopspam(ctx):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_owner(bot_index, ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "You are not an owner.", discord.Color.red()))
            return
        if channel_spam_active[bot_index] is None:
            await ctx.send(embed=get_embed("⚠️ No Active Spam", "No channel spam is currently running.", discord.Color.orange()))
            return
        channel_spam_active[bot_index]["stop_flag"].set()
        channel_spam_active[bot_index] = None
        await ctx.send(embed=get_embed("🛑 **Channel Spam Stopped**", "All channel spam has been stopped.", discord.Color.red()))

    @bot.command(name="fuckvc")
    async def fuckvc(ctx, vc_id: int):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_owner(bot_index, ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "You are not an owner.", discord.Color.red()))
            return

        if not ctx.guild:
            await ctx.send(embed=get_embed("❌ Error", "This command must be used in a server.", discord.Color.red()))
            return

        stop_flag = threading.Event()
        fuckvc_active[bot_index] = {
            "vc_id": vc_id,
            "guild_id": ctx.guild.id,
            "stop_flag": stop_flag
        }

        await ctx.send(embed=get_embed("🔊 **VC Fuck Started**", f"VC ID: `{vc_id}`", discord.Color.green()))

        async def vc_loop():
            while not stop_flag.is_set():
                try:
                    vc_channel = bot.get_channel(vc_id)
                    if vc_channel and hasattr(vc_channel, 'connect'):
                        vc_conn = await vc_channel.connect()
                        stop_flag.wait(random.uniform(1, 3))
                        await vc_conn.disconnect(force=True)
                except:
                    pass
                stop_flag.wait(random.uniform(1, 3))

        asyncio.ensure_future(vc_loop())

    @bot.command(name="fuckvcstop")
    async def fuckvcstop(ctx):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_owner(bot_index, ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "You are not an owner.", discord.Color.red()))
            return
        if fuckvc_active[bot_index] is None:
            await ctx.send(embed=get_embed("⚠️ No Active VC Fuck", "No VC fuck is currently running.", discord.Color.orange()))
            return
        fuckvc_active[bot_index]["stop_flag"].set()
        fuckvc_active[bot_index] = None
        for vc in bot.voice_clients:
            try:
                await vc.disconnect(force=True)
            except:
                pass
        await ctx.send(embed=get_embed("🛑 **VC Fuck Stopped**", "All VC fuck has been stopped.", discord.Color.red()))

    @bot.command(name="delete")
    async def delete(ctx, amount: int):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_owner(bot_index, ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "You are not an owner.", discord.Color.red()))
            return
        if not ctx.guild:
            await ctx.send(embed=get_embed("❌ Error", "This command must be used in a server.", discord.Color.red()))
            return
        try:
            deleted = await ctx.channel.purge(limit=min(amount, 100))
            await ctx.send(embed=get_embed("🗑️ **Messages Deleted**", f"Deleted `{len(deleted)}` messages.", discord.Color.green()))
        except Exception as e:
            await ctx.send(embed=get_embed("❌ Delete Failed", f"Error: {str(e)}", discord.Color.red()))

    @bot.command(name="ban")
    async def ban(ctx, user_id: int):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_owner(bot_index, ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "You are not an owner.", discord.Color.red()))
            return
        if not ctx.guild:
            await ctx.send(embed=get_embed("❌ Error", "This command must be used in a server.", discord.Color.red()))
            return
        try:
            user = await bot.fetch_user(user_id)
            await ctx.guild.ban(user, reason=f"Banned by {ctx.author}")
            await ctx.send(embed=get_embed("🔨 **User Banned**", f"Banned `{user.name}` (`{user_id}`)", discord.Color.green()))
        except Exception as e:
            await ctx.send(embed=get_embed("❌ Ban Failed", f"Error: {str(e)}", discord.Color.red()))

    @bot.command(name="kick")
    async def kick(ctx, user_id: int):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_owner(bot_index, ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "You are not an owner.", discord.Color.red()))
            return
        if not ctx.guild:
            await ctx.send(embed=get_embed("❌ Error", "This command must be used in a server.", discord.Color.red()))
            return
        try:
            user = await bot.fetch_user(user_id)
            member = ctx.guild.get_member(user_id) or await ctx.guild.fetch_member(user_id)
            await member.kick(reason=f"Kicked by {ctx.author}")
            await ctx.send(embed=get_embed("👢 **User Kicked**", f"Kicked `{user.name}` (`{user_id}`)", discord.Color.green()))
        except Exception as e:
            await ctx.send(embed=get_embed("❌ Kick Failed", f"Error: {str(e)}", discord.Color.red()))

    @bot.command(name="mute")
    async def mute(ctx, user_id: int):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_owner(bot_index, ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "You are not an owner.", discord.Color.red()))
            return
        # Add to muted set
        muted_users[bot_index].add(user_id)
        await ctx.send(embed=get_embed("🔇 **User Muted**", f"Muted `{user_id}`", discord.Color.green()))

    @bot.command(name="updatepfp")
    async def updatepfp(ctx, image_url: str):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_owner(bot_index, ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "You are not an owner.", discord.Color.red()))
            return
        try:
            resp = requests.get(image_url)
            if resp.status_code == 200:
                await bot.user.edit(avatar=resp.content)
                await ctx.send(embed=get_embed("🖼️ **Profile Picture Updated**", "Successfully changed PFP.", discord.Color.green()))
            else:
                await ctx.send(embed=get_embed("❌ Failed", "Could not fetch image from URL.", discord.Color.red()))
        except Exception as e:
            await ctx.send(embed=get_embed("❌ PFP Update Failed", f"Error: {str(e)}", discord.Color.red()))

    @bot.command(name="updatebio")
    async def updatebio(ctx, *, bio: str):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_owner(bot_index, ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "You are not an owner.", discord.Color.red()))
            return
        try:
            await bot.user.edit(bio=bio)
            await ctx.send(embed=get_embed("📝 **Bio Updated**", f"Bio set to: `{bio[:100]}`", discord.Color.green()))
        except Exception as e:
            await ctx.send(embed=get_embed("❌ Bio Update Failed", f"Error: {str(e)}", discord.Color.red()))

    @bot.command(name="updatelis")
    async def updatelis(ctx, *, text: str):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_owner(bot_index, ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "You are not an owner.", discord.Color.red()))
            return
        try:
            await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=text))
            await ctx.send(embed=get_embed("🎵 **Listening Status Updated**", f"Now listening to: `{text[:100]}`", discord.Color.green()))
        except Exception as e:
            await ctx.send(embed=get_embed("❌ Status Update Failed", f"Error: {str(e)}", discord.Color.red()))

    # ============================================================
    # OWNER MANAGEMENT (Primary only)
    # ============================================================

    @bot.command(name="ownset")
    async def ownset(ctx, user_id: int):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_primary_owner(ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "Only primary owners can manage secondary owners.", discord.Color.red()))
            return
        secondary_owners[bot_index].add(user_id)
        await ctx.send(embed=get_embed("👑 **Secondary Owner Added**", f"User `{user_id}` is now a secondary owner.", discord.Color.green()))

    @bot.command(name="ownremove")
    async def ownremove(ctx, user_id: int):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_primary_owner(ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "Only primary owners can manage secondary owners.", discord.Color.red()))
            return
        if user_id in secondary_owners[bot_index]:
            secondary_owners[bot_index].discard(user_id)
            await ctx.send(embed=get_embed("👑 **Secondary Owner Removed**", f"User `{user_id}` is no longer an owner.", discord.Color.green()))
        else:
            await ctx.send(embed=get_embed("⚠️ Not Found", f"User `{user_id}` is not a secondary owner.", discord.Color.orange()))

    @bot.command(name="listowns")
    async def listowns(ctx):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_owner(bot_index, ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "You are not an owner.", discord.Color.red()))
            return
        primaries = [f"<@{uid}> (`{uid}`)" for uid in PRIMARY_OWNERS]
        secondaries = [f"<@{uid}> (`{uid}`)" for uid in secondary_owners[bot_index]]
        text = "**👑 Primary Owners:**\n" + "\n".join(primaries) if primaries else "No primary owners."
        text += "\n\n**👑 Secondary Owners:**\n" + "\n".join(secondaries) if secondaries else "\n\nNo secondary owners."
        await ctx.send(embed=get_embed("📋 **Owner List**", text, discord.Color.blue()))

    return bot, token

# ============================================================
# MAIN — Run all bots
# ============================================================

async def main():
    print(f"[✓] Starting {len(TOKENS)} bot(s)...")
    
    bots = []
    for i, token in enumerate(TOKENS):
        print(f"[...] Initializing bot {i+1}/{len(TOKENS)}...")
        bot, t = make_bot(token, i)
        bots.append((bot, t))
    
    print(f"[✓] All bots initialized. Starting login...")
    
    await asyncio.gather(*[bot.start(token) for bot, token in bots])

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[!] Shutting down...")
    except Exception as e:
        print(f"[FATAL] Unhandled exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
