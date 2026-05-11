import os
import sys
import asyncio
import random
import threading
import requests
import discord
from discord.ext import commands

# ============================================================
# CONFIGURATION - Loaded from Environment Variables
# ============================================================

TOKENS_ENV = os.environ.get("TOKENS", "")
if not TOKENS_ENV.strip():
    print("[FATAL] TOKENS environment variable is empty or not set!")
    print("[FATAL] Please set TOKENS in your Render environment variables.")
    print("[FATAL] Example: TOKENS=bot_token_1,bot_token_2,bot_token_3")
    sys.exit(1)

TOKENS = [t.strip() for t in TOKENS_ENV.split(",") if t.strip()]
print(f"[INFO] Loaded {len(TOKENS)} bot token(s) from environment.")

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

ALLOWED_CHANNELS_ENV = os.environ.get("ALLOWED_CHANNELS", "")
ALLOWED_CHANNELS = []
if ALLOWED_CHANNELS_ENV.strip():
    ALLOWED_CHANNELS = [int(cid.strip()) for cid in ALLOWED_CHANNELS_ENV.split(",") if cid.strip().isdigit()]
    print(f"[INFO] Allowed channels: {ALLOWED_CHANNELS}")
else:
    print("[INFO] No ALLOWED_CHANNELS set - bots will operate in ALL channels.")

# ============================================================
# GLOBAL STATE
# ============================================================

secondary_owners = {}
dm_spam_active = {}
channel_spam_active = {}
fuckvc_active = {}
muted_users = {}

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def is_allowed_channel(channel_id):
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

    # Initialize state
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
        await bot.change_presence(status=discord.Status.online)

    @bot.event
    async def on_message(message):
        if message.author.id == bot.user.id:
            return
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
`!dmspam @user <message>` - Start DM spam
`!dmspamstop` - Stop DM spam

**💬 Channel Commands**
`!spam <channel_id> <message>` - Start channel spam
`!stopspam` - Stop channel spam

**🔊 Voice Commands**
`!fuckvc @user` - Rapidly move user between all VCs
`!fuckvcstop` - Stop VC fuck

**🛡️ Moderation**
`!delete <amount>` - Delete messages
`!ban @user` - Ban a user
`!kick @user` - Kick a user
`!mute @user` - Mute a user

**👤 Profile**
`!updatepfp <image_url>` - Update profile picture
`!updatebio <text>` - Update bio
`!updatelis <text>` - Update listening status

**👑 Owner Management (Primary only)**
`!ownset @user` - Add secondary owner
`!ownremove @user` - Remove secondary owner
`!listowns` - List all owners
        """.strip()
        await ctx.send(embed=get_embed("📚 **Help Menu**", help_text, discord.Color.green()))

    @bot.command(name="dmspam")
    async def dmspam(ctx, user: discord.User, *, message: str):
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
            "target_id": user.id,
            "message": message,
            "delay": delay,
            "stop_flag": stop_flag
        }

        await ctx.send(embed=get_embed("✅ **DM Spam Started**", f"Target: {user.mention}\nDelay: `{delay}s`\nMessage: `{message[:50]}...`", discord.Color.green()))

        async def spam_loop():
            while not stop_flag.is_set():
                try:
                    await user.send(message)
                except discord.Forbidden:
                    await ctx.send(embed=get_embed("⚠️ DM Error", "Cannot DM this user (DMs closed or blocked).", discord.Color.orange()))
                    break
                except Exception as e:
                    await ctx.send(embed=get_embed("⚠️ DM Error", f"Failed: {str(e)}", discord.Color.orange()))
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

        await ctx.send(embed=get_embed("✅ **Channel Spam Started**", f"Channel: `{channel_id}`\nDelay: `{delay}s`", discord.Color.green()))

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
                    await ctx.send(embed=get_embed("⚠️ Error", "Missing permissions.", discord.Color.orange()))
                    break
                except Exception as e:
                    await ctx.send(embed=get_embed("⚠️ Error", f"Failed: {str(e)}", discord.Color.orange()))
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
            await ctx.send(embed=get_embed("⚠️ No Active Spam", "No channel spam is running.", discord.Color.orange()))
            return
        channel_spam_active[bot_index]["stop_flag"].set()
        channel_spam_active[bot_index] = None
        await ctx.send(embed=get_embed("🛑 **Channel Spam Stopped**", "All channel spam stopped.", discord.Color.red()))

    @bot.command(name="fuckvc")
    async def fuckvc(ctx, member: discord.Member):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_owner(bot_index, ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "You are not an owner.", discord.Color.red()))
            return
        if not ctx.guild:
            await ctx.send(embed=get_embed("❌ Error", "Use this in a server.", discord.Color.red()))
            return

        stop_flag = threading.Event()
        fuckvc_active[bot_index] = {
            "user_id": member.id,
            "guild_id": ctx.guild.id,
            "stop_flag": stop_flag
        }

        await ctx.send(embed=get_embed("🔊 **VC Fuck Started**", f"Target: {member.mention}\nMoving between all voice channels!", discord.Color.green()))

        async def vc_fuck_loop():
            while not stop_flag.is_set():
                try:
                    guild = bot.get_guild(ctx.guild.id)
                    if not guild:
                        break
                    voice_channels = [vc for vc in guild.voice_channels]
                    if not voice_channels:
                        break
                    current_member = guild.get_member(member.id)
                    if not current_member:
                        break
                    for vc in voice_channels:
                        if stop_flag.is_set():
                            break
                        try:
                            await current_member.move_to(vc, reason=f"VC Fuck by {ctx.author}")
                        except:
                            pass
                        await asyncio.sleep(0.3)
                except:
                    break

        asyncio.ensure_future(vc_fuck_loop())

    @bot.command(name="fuckvcstop")
    async def fuckvcstop(ctx):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_owner(bot_index, ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "You are not an owner.", discord.Color.red()))
            return
        if fuckvc_active[bot_index] is None:
            await ctx.send(embed=get_embed("⚠️ No Active VC Fuck", "No VC fuck is running.", discord.Color.orange()))
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
            await ctx.send(embed=get_embed("❌ Error", "Use this in a server.", discord.Color.red()))
            return
        try:
            deleted = await ctx.channel.purge(limit=min(amount, 100))
            await ctx.send(embed=get_embed("🗑️ **Deleted**", f"Deleted `{len(deleted)}` messages.", discord.Color.green()))
        except Exception as e:
            await ctx.send(embed=get_embed("❌ Failed", f"Error: {str(e)}", discord.Color.red()))

    @bot.command(name="ban")
    async def ban(ctx, member: discord.Member):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_owner(bot_index, ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "You are not an owner.", discord.Color.red()))
            return
        if not ctx.guild:
            await ctx.send(embed=get_embed("❌ Error", "Use this in a server.", discord.Color.red()))
            return
        try:
            await member.ban(reason=f"Banned by {ctx.author}")
            await ctx.send(embed=get_embed("🔨 **Banned**", f"Banned {member.mention}", discord.Color.green()))
        except Exception as e:
            await ctx.send(embed=get_embed("❌ Failed", f"Error: {str(e)}", discord.Color.red()))

    @bot.command(name="kick")
    async def kick(ctx, member: discord.Member):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_owner(bot_index, ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "You are not an owner.", discord.Color.red()))
            return
        if not ctx.guild:
            await ctx.send(embed=get_embed("❌ Error", "Use this in a server.", discord.Color.red()))
            return
        try:
            await member.kick(reason=f"Kicked by {ctx.author}")
            await ctx.send(embed=get_embed("👢 **Kicked**", f"Kicked {member.mention}", discord.Color.green()))
        except Exception as e:
            await ctx.send(embed=get_embed("❌ Failed", f"Error: {str(e)}", discord.Color.red()))

    @bot.command(name="mute")
    async def mute(ctx, member: discord.Member):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_owner(bot_index, ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "You are not an owner.", discord.Color.red()))
            return
        muted_users[bot_index].add(member.id)
        await ctx.send(embed=get_embed("🔇 **Muted**", f"Muted {member.mention}", discord.Color.green()))

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
                await ctx.send(embed=get_embed("🖼️ **PFP Updated**", "Successfully changed profile picture.", discord.Color.green()))
            else:
                await ctx.send(embed=get_embed("❌ Failed", "Could not fetch image.", discord.Color.red()))
        except Exception as e:
            await ctx.send(embed=get_embed("❌ Failed", f"Error: {str(e)}", discord.Color.red()))

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
            await ctx.send(embed=get_embed("❌ Failed", f"Error: {str(e)}", discord.Color.red()))

    @bot.command(name="updatelis")
    async def updatelis(ctx, *, text: str):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_owner(bot_index, ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "You are not an owner.", discord.Color.red()))
            return
        try:
            await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=text))
            await ctx.send(embed=get_embed("🎵 **Status Updated**", f"Now listening to: `{text[:100]}`", discord.Color.green()))
        except Exception as e:
            await ctx.send(embed=get_embed("❌ Failed", f"Error: {str(e)}", discord.Color.red()))

    @bot.command(name="ownset")
    async def ownset(ctx, user: discord.User):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_primary_owner(ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "Only primary owners can manage secondary owners.", discord.Color.red()))
            return
        secondary_owners[bot_index].add(user.id)
        await ctx.send(embed=get_embed("👑 **Owner Added**", f"{user.mention} is now a secondary owner.", discord.Color.green()))

    @bot.command(name="ownremove")
    async def ownremove(ctx, user: discord.User):
        if not is_allowed_channel(ctx.channel.id):
            return
        if not is_primary_owner(ctx.author.id):
            await ctx.send(embed=get_embed("❌ Access Denied", "Only primary owners can manage secondary owners.", discord.Color.red()))
            return
        if user.id in secondary_owners[bot_index]:
            secondary_owners[bot_index].discard(user.id)
            await ctx.send(embed=get_embed("👑 **Owner Removed**", f"{user.mention} is no longer an owner.", discord.Color.green()))
        else:
            await ctx.send(embed=get_embed("⚠️ Not Found", f"{user.mention} is not a secondary owner.", discord.Color.orange()))

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
# MAIN
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
