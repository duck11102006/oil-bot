import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import aiohttp
import certifi
import ssl
from flask import Flask
import threading
from discord.http import Route
import pymongo # Thêm thư viện này ở đầu file

# --- RENDER COMPATIBILITY LAYER ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    # Render yêu cầu bind vào cổng được cấp phát qua biến môi trường PORT
    port = int(os.environ.get("PORT", 7860))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = threading.Thread(target=run)
    t.daemon = True
    t.start()

# Khởi chạy Web Server để Render không tắt Bot
keep_alive()

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True # Đảm bảo đã bật Message Content Intent
bot = commands.Bot(command_prefix=".", intents=intents)

# --- 1. MONGODB SETUP ---
# Lấy link kết nối từ Environment Variable của Render
MONGO_URL = os.getenv("MONGO_URL")
cluster = pymongo.MongoClient(MONGO_URL)
db = cluster["OilBotDB"]
collection = db["profiles"]

def load_profiles():
    """Tải tất cả profiles từ MongoDB (không dùng file JSON nữa)."""
    return collection

def get_user_profile(user_id):
    """Lấy thông tin một người dùng cụ thể."""
    return collection.find_one({"_id": str(user_id)})

def save_profile(user_id, petrol_s, energy_s):
    """Lưu hoặc cập nhật dữ liệu vào MongoDB."""
    collection.update_one(
        {"_id": str(user_id)},
        {"$set": {
            "petrol_s": petrol_s.upper(),
            "energy_s": energy_s.upper()
        }},
        upsert=True # Nếu chưa có thì tạo mới, có rồi thì ghi đè
    )

# --- 2. HELPER FUNCTIONS ---

def parse_value(val_str):
    if not val_str: return 0.0
    val_str = str(val_str).upper().strip().replace("$", "").replace(",", "")
    multipliers = {'K': 1e3, 'M': 1e6, 'B': 1e9, 'T': 1e12}
    if val_str[-1] in multipliers:
        unit = val_str[-1]
        try: return float(val_str[:-1]) * multipliers[unit]
        except: return 0.0
    try: return float(val_str)
    except: return 0.0

def format_value(num):
    if abs(num) < 1000: return f"{num:,.2f}"
    for unit in ['', 'K', 'M', 'B', 'T']:
        if abs(num) < 1000.0: return f"{num:,.2f}{unit}"
        num /= 1000.0
    return f"{num:,.2f}P"

def format_time(seconds):
    if seconds <= 0: return "Instant"
    if seconds == float('inf'): return "Never"
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, sec = divmod(rem, 60)
    parts = []
    if days > 0: parts.append(f"{days}d")
    if hours > 0: parts.append(f"{hours}h")
    if minutes > 0: parts.append(f"{minutes}m")
    if sec > 0 or not parts: parts.append(f"{sec}s")
    return " ".join(parts)

DRILL_DATA = [
    ("Basic Drill", 500), ("Strong Drill", 1800), ("Enhanced Drill", 3600),
    ("Speed Drill", 7200), ("Reinforced Drill", 12000), ("Industrial Drill", 20000),
    ("Double Industrial Drill", 30000), ("Turbo Drill", 80000), ("Mega Drill", 140000),
    ("Mega Emerald Drill", 400000), ("Hell Drill", 1225000), ("Plasma Drill", 4500000),
    ("Huge Long Drill", 40000000), ("Mega Plasma Drill", 95000000), ("Multi Drill", 280000000),
    ("Lava Drill", 900000000), ("Ice Plasma Drill", 2400000000), ("Crystal Drill", 9000000000),
    ("Diamond Drill", 27500000000), ("Ruby Drill", 85500000000), ("Fusion Drill", 187500000000),
    ("Uranium Drill", 437500000000), ("Radium Drill", 810000000000), ("Palladium Drill", 1250000000000),
    ("Thorium Drill", 2100000000000)
]

# --- 4. UI SELECTION CLASSES ---
class DrillSelect(discord.ui.Select):
    def __init__(self, eps, amount, profile_petrol, user_name):
        self.eps, self.amount, self.profile_petrol, self.user_name = eps, amount, profile_petrol, user_name
        options = [discord.SelectOption(label=d[0], value=str(d[1])) for d in DRILL_DATA]
        super().__init__(placeholder="Select a drill type...", options=options)

    async def callback(self, interaction: discord.Interaction):
        total_cost = float(self.values[0]) * self.amount
        drill_name = [o.label for o in self.options if o.value == self.values[0]][0]
        time_needed = total_cost / self.eps if self.eps > 0 else float('inf')
        
        embed = discord.Embed(title="⚙️ Drill Cost Calculator", color=0x2f3136)
        embed.set_author(name="Calculation Complete")
        embed.add_field(name="Selected Drill", value=f"**{drill_name}**\n(x{self.amount})", inline=True)
        embed.add_field(name="Cost", value=f"```\n$\n{format_value(total_cost)}\n```", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="Petrol/s", value=f"```\n{self.profile_petrol}\n```", inline=True)
        embed.add_field(name="Current EPS", value=f"```\n$\n{format_value(self.eps)}/s\n
```", inline=True)
        embed.add_field(name="⏳ Time Needed", value=f"```ansi\n\u001b[1;33m{format_time(time_needed)}\u001b[0m\n```", inline=False)
        embed.set_footer(text=f"Requested by {self.user_name}")
        await interaction.response.edit_message(embed=embed, view=None)

class GoldenDrillSelect(discord.ui.Select):
    def __init__(self, eps, amount, energy_s, target_energy_base, energy_pct, profile_petrol, user_name):
        self.eps = eps * energy_pct
        self.amount = amount
        self.energy_s = energy_s
        self.target_energy_base = target_energy_base 
        self.energy_pct = energy_pct
        self.profile_petrol = profile_petrol
        self.user_name = user_name
        options = [discord.SelectOption(label=f"Golden {d[0]}", value=str(d[1])) for d in DRILL_DATA]
        super().__init__(placeholder="Select a Golden Drill...", options=options)

    async def callback(self, interaction: discord.Interaction):
        golden_total_cost = (float(self.values[0]) * 4) * self.amount
        drill_name = [o.label for o in self.options if o.value == self.values[0]][0]
        total_energy_needed = self.target_energy_base * self.amount
        t_money = golden_total_cost / self.eps if self.eps > 0 else float('inf')
        t_energy = total_energy_needed / self.energy_s if self.energy_s > 0 else float('inf')
        final_wait = max(t_money, t_energy)
        
        embed = discord.Embed(title="✨ Golden Drill Cost Calculator", color=0xf1c40f)
        embed.set_author(name="Calculation Complete")
        embed.add_field(name="Selected Drill", value=f"**{drill_name}**\n(x{self.amount})", inline=True)
        embed.add_field(name="Golden Cost", value=f"```\n$\n{format_value(golden_total_cost)}\n```", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="Petrol/s", value=f"```\n{self.profile_petrol}\n```", inline=True)
        embed.add_field(name="Adjusted EPS", value=f"```\n$\n{format_value(self.eps)}/s\n
```", inline=True)
        embed.add_field(name="Energy Eff.", value=f"```\n{int(self.energy_pct*100)}%\n```", inline=True)
        details = f"Money wait: {format_time(t_money)}\nEnergy wait: {format_time(t_energy)}"
        embed.add_field(name="📊 Calculation Details", value=f"```\n{details}\n```", inline=False)
        embed.add_field(name="⏳ Total Time Needed", value=f"```ansi\n\u001b[1;33m{format_time(final_wait)}\u001b[0m\n
```", inline=False)
        embed.set_footer(text=f"Requested by {self.user_name}")
        await interaction.response.edit_message(embed=embed, view=None)

# --- 5. MAIN COMMANDS ---

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot logged in as {bot.user}")

@bot.tree.command(name="profile_set", description="Configure your personal Petrol and Energy production rates for future calculations.")
@app_commands.describe(
    petrol_s="Your current Petrol production per second (e.g., 1.2M, 800K).",
    energy_s="Your current Energy production per second (e.g., 50, 100)."
)
async def profile_set(interaction: discord.Interaction, petrol_s: str, energy_s: str):
    await interaction.response.defer(thinking=True, ephemeral=True)
    save_profile(interaction.user.id, petrol_s, energy_s)
    await interaction.followup.send(f"✅ Profile updated: **{petrol_s}/s Petrol** | **{energy_s}/s Energy**")

@bot.tree.command(name="drillcost", description="Calculate the total cost and time required to purchase a specific amount of drills.")
@app_commands.describe(
    sell_price="The current market selling price per unit of petrol.",
    money_boost="Your total money boost percentage (e.g., 485 for 485%).",
    amount="The quantity of drills you want to buy (defaults to 1)."
)
async def drillcost(interaction: discord.Interaction, sell_price: float, money_boost: float, amount: int = 1):
    await interaction.response.defer(thinking=True)
    data = get_user_profile(interaction.user.id)
    if not data: return await interaction.followup.send("❌ Please setup your profile first using `/profile_set`!")
    p_str = data["petrol_s"]
    eps = parse_value(p_str) * sell_price * (money_boost / 100)
    view = discord.ui.View(timeout=None).add_item(DrillSelect(eps, amount, p_str, interaction.user.name))
    await interaction.followup.send(embed=discord.Embed(title="⚙️ Drill Cost Calculator", description=f"Quantity: **{amount}**. Please select a drill from the menu below:", color=0x2f3136), view=view)

@bot.tree.command(name="golden_drillcost", description="Calculate Golden Drill cost (4x) and determine the wait time based on Money vs Energy.")
@app_commands.describe(
    sell_price="The current market selling price per unit of petrol.",
    money_boost="Your total money boost percentage.",
    amount="The number of Golden Drills you plan to purchase.",
    energy_needed="Target Energy level (Choices: 10000 (15%), 19000 (40%), 24000 (75%), 28000 (100%))."
)
async def golden_drillcost(interaction: discord.Interaction, sell_price: float, money_boost: float, amount: int = 1, energy_needed: int = 28000):
    await interaction.response.defer(thinking=True)
    energy_map = {10000: 0.15, 19000: 0.40, 24000: 0.75, 28000: 1.0}
    if energy_needed not in energy_map: return await interaction.followup.send("❌ Invalid energy value! Use 10000, 19000, 24000, or 28000.")
    data = get_user_profile(interaction.user.id)
    if not data: return await interaction.followup.send("❌ Setup profile first!")
    p_val, e_s_val = parse_value(data["petrol_s"]), parse_value(data["energy_s"])
    if e_s_val <= 0: return await interaction.followup.send("❌ Energy/s in profile must be > 0.")
    eps = p_val * sell_price * (money_boost / 100)
    view = discord.ui.View(timeout=None).add_item(GoldenDrillSelect(eps, amount, e_s_val, energy_needed, energy_map[energy_needed], data["petrol_s"], interaction.user.name))
    await interaction.followup.send(embed=discord.Embed(title="✨ Golden Drill Calculator", description=f"Quantity: **{amount}** | Target: **{energy_needed} Energy**", color=0xf1c40f), view=view)

@bot.tree.command(name="sellgas", description="Estimate the immediate profit gained from selling a specific amount of petrol.")
@app_commands.describe(
    petrol="The specific amount of petrol to sell (e.g., 500B, 10T).",
    sell_price="The current selling price per unit.",
    money_boost="Your total money boost percentage (e.g., 485)."
)
async def sellgas(interaction: discord.Interaction, petrol: str, sell_price: float, money_boost: float):
    await interaction.response.defer(thinking=True)
    try:
        p_val = parse_value(petrol)
        if p_val is None or p_val == 0:
            await interaction.followup.send("❌ Invalid petrol amount! Use K, M, B, or T.", ephemeral=True)
            return
        boost_multi = money_boost / 100
        total = p_val * sell_price * boost_multi
        embed = discord.Embed(title="⛽ Petrol Calculator", description="**Sell Gas — Result**", color=0x2f3136)
        embed.add_field(name="⛽ Petrol", value=f"```\n{petrol.upper()}\n```", inline=True)
        embed.add_field(name="💵 Price", value=f"```\n$\n{sell_price:,.2f}\n```", inline=True)
        embed.add_field(name="🚀 Boost", value=f"```\n{money_boost:.1f}%\n(x{boost_multi:.2f})\n```", inline=True)
        res_text = f"+ $ {format_value(total)}"
        embed.add_field(name="💰 Earnings", value=f"```ansi\n\u001b[1;32m{res_text}\u001b[0m\n
```", inline=False)
        embed.set_footer(text=f"Requested by {interaction.user.name}", icon_url=interaction.user.display_avatar.url)
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {str(e)}", ephemeral=True)

@bot.tree.command(name="calculate", description="View a detailed time-based breakdown of your earnings (Second, Minute, Hour, and Daily).")
@app_commands.describe(
    sell_price="Market price per petrol unit.",
    money_boost="Total boost percentage applied to your income.",
    petrol_s="Override your profile Petrol/s rate (Optional).",
    playtime_hours="Active hours per day for the daily summary (Default: 24)."
)
async def calculate(interaction: discord.Interaction, sell_price: float, money_boost: float, petrol_s: str = None, playtime_hours: float = 24.0):
    await interaction.response.defer(thinking=True)
    user_data = get_user_profile(interaction.user.id)
    p_str = petrol_s if petrol_s else (user_data["petrol_s"] if user_data else "0")
    p_val = parse_value(p_str)
    boost_multi = money_boost / 100
    eps = p_val * sell_price * boost_multi
    embed = discord.Embed(title="⛽ Petrol Calculator", description="**Calculation Complete**", color=0x2f3136)
    embed.add_field(name="⛽ Petrol/s", value=f"```\n{p_str}\n```", inline=True)
    embed.add_field(name="💵 Price", value=f"```\n$ {sell_price:,.2f}\n```", inline=True)
    embed.add_field(name="🚀 Boost", value=f"```\n{money_boost}% \n(x{boost_multi:.2f})\n```", inline=True)
    embed.add_field(name="⏱️ Per Second", value=f"```\n$ {format_value(eps)}\n
```", inline=True)
    embed.add_field(name="🕒 Per Minute", value=f"```\n$ {format_value(eps*60)}\n```", inline=True)
    embed.add_field(name="📈 Per Hour", value=f"```\n$ {format_value(eps*3600)}\n
```", inline=True)
    total_money = eps * 3600 * playtime_hours
    total_petrol = p_val * 3600 * playtime_hours
    summary_text = f"+ $ {format_value(total_money)}\n+ {format_value(total_petrol)} petrol"
    embed.add_field(name=f"📅 Daily ({playtime_hours}h)", value=f"```ansi\n\u001b[1;32m{summary_text}\u001b[0m\n```", inline=False)
    embed.set_footer(text=f"Requested by {interaction.user.name}", icon_url=interaction.user.display_avatar.url)
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="target_cash", description="Calculate exactly how long you need to wait to reach a specific financial goal.")
@app_commands.describe(
    target="The amount of money you want to earn (e.g., 500B, 12.5T).",
    sell_price="Market price per petrol unit.",
    money_boost="Total boost percentage."
)
async def target_cash(interaction: discord.Interaction, target: str, sell_price: float, money_boost: float):
    await interaction.response.defer(thinking=True)
    data = get_user_profile(interaction.user.id)
    if not data: return await interaction.followup.send("❌ Setup profile first!")
    target_val = parse_value(target)
    eps = parse_value(data["petrol_s"]) * sell_price * (money_boost / 100)
    time_needed = target_val / eps if eps > 0 else float('inf')
    embed = discord.Embed(title="🎯 Target Cash Calculator", color=0x2ecc71)
    embed.add_field(name="Target", value=f"```\n$ {target.upper()}\n
```", inline=True)
    embed.add_field(name="Wait Time", value=f"```ansi\n\u001b[1;33m{format_time(time_needed)}\u001b[0m\n```", inline=True)
    await interaction.followup.send(embed=embed)

async def main():
    # Cấu hình SSL an toàn để tránh lỗi ConnectionReset
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        bot.http.connector = connector
        async with bot:
            token = os.getenv('DISCORD_TOKEN')
            if not token:
                print("❌ ERROR: DISCORD_TOKEN not found!")
                return
            print("🚀 Bot starting...")
            await bot.start(token)

if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
