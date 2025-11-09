import os
import asyncio
import asyncpg
from datetime import datetime, date
from zoneinfo import ZoneInfo
from discord.ext import commands, tasks
import discord
from dotenv import load_dotenv

# === Load environment variables ===
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# === Setup timezone (Asia/Jakarta / GMT+7) ===
WIB = ZoneInfo("Asia/Jakarta")

# === Setup intents ===
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

# === Connect to PostgreSQL ===
async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS todos (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            task_date DATE NOT NULL,
            task TEXT NOT NULL,
            done BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    await conn.close()

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user.name}")
    await init_db()

# === Add a task ===
@bot.command()
async def add(ctx, date_str: str = "", *, task: str = ""):
    """
    Tambah tugas untuk tanggal tertentu (default: hari ini WIB).
    Contoh:
    - !add ngerjain PR
    - !add 2025-11-10 nonton konser
    """
    user_id = ctx.author.id
    now = datetime.now(WIB)

    # Validasi input
    if task is None:
        # Jika user tidak menyertakan task
        await ctx.send("⚠️ Contoh penggunaan:\n`!add [YYYY-MM-DD opsional] <deskripsi tugas>`")
        return

    # Cek apakah argumen pertama adalah tanggal
    task_date = None
    if date_str:
        try:
            task_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            # Jika format tanggal tidak valid, anggap itu bagian dari task
            task_date = now.date()
            task = f"{date_str} {task}"

    # Jika tidak ada tanggal, pakai hari ini (WIB)
    if task_date is None:
        task_date = now.date()

    # Simpan ke database
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(
        "INSERT INTO todos (user_id, task_date, task, done, created_at) VALUES ($1, $2, $3, FALSE, $4);",
        user_id, task_date, task, now
    )
    await conn.close()

    await ctx.send(f"📝 Ditambahkan: **{task}** untuk **{task_date}** — WIB {now.strftime('%H:%M:%S')}")

# === List tasks (can choose date) ===
@bot.command()
async def list(ctx, date_str: str = ""):
    """
    Tampilkan daftar tugas untuk tanggal tertentu (format YYYY-MM-DD).
    Jika tidak ada tanggal, tampilkan tugas untuk hari ini (WIB).
    Contoh:
    - !list
    - !list 2025-11-10
    """
    user_id = ctx.author.id
    now = datetime.now(WIB)
    today = now.date()

    # Parsing tanggal input (kalau ada)
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            await ctx.send("⚠️ Format tanggal tidak valid. Gunakan format **YYYY-MM-DD**.")
            return
    else:
        target_date = today

    # Ambil data dari database
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch(
        """
        SELECT id, task, done 
        FROM todos 
        WHERE user_id = $1 AND task_date = $2 
        ORDER BY id;
        """,
        user_id, target_date
    )
    await conn.close()

    # Jika tidak ada tugas
    if not rows:
        await ctx.send(f"✨ Tidak ada tugas untuk **{target_date}** (WIB).")
        return

    # Buat daftar pesan
    msg = [f"📅 **Tugas untuk {target_date} (WIB):**"]
    for row in rows:
        status = "✅" if row["done"] else "☐"
        msg.append(f"{status} {row['task']} (ID: {row['id']})")

    msg.append(f"\n🕒 Waktu server: {now.strftime('%Y-%m-%d %H:%M:%S')} WIB")

    await ctx.send("\n".join(msg))

# === Mark as done ===
@bot.command()
async def done(ctx, *args):
    """
    Tandai tugas sebagai selesai.
    Bisa berdasarkan ID atau (tanggal + sebagian judul).
    Contoh:
    - !done 3
    - !done 2025-11-09 nonton hsr
    """
    user_id = ctx.author.id
    conn = await asyncpg.connect(DATABASE_URL)

    # Jika hanya 1 argumen dan berupa angka → anggap ID
    if len(args) == 1 and args[0].isdigit():
        task_id = int(args[0])
        result = await conn.execute("UPDATE todos SET done = TRUE WHERE id = $1 AND user_id = $2;", task_id, user_id)
        await conn.close()

        if result == "UPDATE 1":
            await ctx.send(f"✅ Tugas dengan ID {task_id} telah ditandai selesai!")
        else:
            await ctx.send("❌ ID tugas tidak ditemukan.")
        return

    # Jika format tanggal + nama tugas
    if len(args) >= 2:
        try:
            target_date = datetime.strptime(args[0], "%Y-%m-%d").date()
            task_name = " ".join(args[1:])
        except ValueError:
            await ctx.send("⚠️ Format salah. Gunakan `!done <ID>` atau `!done <YYYY-MM-DD> <judul>`")
            await conn.close()
            return

        result = await conn.execute(
            """
            UPDATE todos 
            SET done = TRUE 
            WHERE user_id = $1 AND task_date = $2 AND task ILIKE $3;
            """,
            user_id, target_date, f"%{task_name}%"
        )
        await conn.close()

        if result == "UPDATE 1":
            await ctx.send(f"✅ Tugas '{task_name}' untuk {target_date} ditandai selesai!")
        else:
            await ctx.send("❌ Tidak ditemukan tugas dengan nama dan tanggal tersebut.")
        return

    await ctx.send("⚠️ Contoh: `!done 3` atau `!done 2025-11-09 masak nasi`")

@bot.command()
async def delete(ctx, *args):
    """
    Hapus tugas berdasarkan ID atau (tanggal + sebagian judul).
    Contoh:
    - !delete 3
    - !delete 2025-11-09 nonton hsr
    """
    user_id = ctx.author.id
    conn = await asyncpg.connect(DATABASE_URL)

    # Jika hanya 1 argumen angka → hapus berdasarkan ID
    if len(args) == 1 and args[0].isdigit():
        task_id = int(args[0])
        result = await conn.execute("DELETE FROM todos WHERE id = $1 AND user_id = $2;", task_id, user_id)
        await conn.close()

        if result == "DELETE 1":
            await ctx.send(f"🗑️ Tugas dengan ID {task_id} telah dihapus.")
        else:
            await ctx.send("❌ ID tugas tidak ditemukan.")
        return

    # Jika format tanggal + nama tugas
    if len(args) >= 2:
        try:
            target_date = datetime.strptime(args[0], "%Y-%m-%d").date()
            task_name = " ".join(args[1:])
        except ValueError:
            await ctx.send("⚠️ Format salah. Gunakan `!delete <ID>` atau `!delete <YYYY-MM-DD> <judul>`")
            await conn.close()
            return

        result = await conn.execute(
            """
            DELETE FROM todos 
            WHERE user_id = $1 AND task_date = $2 AND task ILIKE $3;
            """,
            user_id, target_date, f"%{task_name}%"
        )
        await conn.close()

        if result == "DELETE 1":
            await ctx.send(f"🗑️ Tugas '{task_name}' untuk {target_date} telah dihapus.")
        else:
            await ctx.send("❌ Tidak ditemukan tugas dengan nama dan tanggal tersebut.")
        return

    await ctx.send("⚠️ Contoh: `!delete 3` atau `!delete 2025-11-09 masak nasi`")

# === Delete all tasks for a date ===
@bot.command()
async def clear(ctx, date_str: str = ""):
    """Hapus semua tugas untuk tanggal tertentu (default: hari ini)."""
    user_id = ctx.author.id
    today = datetime.now(WIB).date()

    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else today
    except ValueError:
        await ctx.send("⚠️ Format tanggal tidak valid. Gunakan YYYY-MM-DD.")
        return

    conn = await asyncpg.connect(DATABASE_URL)
    result = await conn.execute("DELETE FROM todos WHERE user_id = $1 AND task_date = $2;", user_id, target_date)
    await conn.close()

    await ctx.send(f"🧹 Semua tugas untuk {target_date} telah dihapus.")

@bot.command()
async def dates(ctx):
    """
    Tampilkan semua tugas yang dimiliki user, dikelompokkan berdasarkan tanggal.
    Format: 📅 YYYY-MM-DD -> list tugas (✅ / ☐)
    """
    user_id = ctx.author.id
    conn = await asyncpg.connect(DATABASE_URL)

    rows = await conn.fetch("""
        SELECT task_date, task, done
        FROM todos
        WHERE user_id = $1
        ORDER BY task_date ASC, id ASC;
    """, user_id)
    await conn.close()

    if not rows:
        await ctx.send("✨ Kamu belum memiliki tugas sama sekali.")
        return

    # Kelompokkan berdasarkan tanggal
    grouped = {}
    for row in rows:
        date_str = row["task_date"].strftime("%Y-%m-%d")
        grouped.setdefault(date_str, []).append(row)

    # Format pesan
    messages = ["📅 **Daftar Semua Tugas Berdasarkan Tanggal (WIB):**"]
    for date_str, tasks in grouped.items():
        messages.append(f"\n📆 {date_str}:")
        for t in tasks:
            status = "✅" if t["done"] else "☐"
            messages.append(f"　{status} {t['task']}")

    # Discord hanya bisa kirim max 2000 karakter per pesan
    message_chunks = []
    current_chunk = ""
    for line in messages:
        if len(current_chunk) + len(line) + 1 > 1900:
            message_chunks.append(current_chunk)
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"
    message_chunks.append(current_chunk)

    for chunk in message_chunks:
        await ctx.send(chunk)    
    
# === Restart bot if needed ===
@bot.command()
@commands.is_owner()
async def restart(ctx):
    """Restart bot (hanya owner)."""
    await ctx.send("🔄 Bot akan restart...")
    await bot.close()
    os.execv(sys.executable, ['python'] + sys.argv)

# === Run bot ===
async def main():
    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())