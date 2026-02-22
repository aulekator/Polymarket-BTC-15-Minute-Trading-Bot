import subprocess
import time
import sys
import os
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def run_bot():
    """Run the bot with auto-restart using the SAME Python environment."""
    
    BOT_SCRIPT = "bot.py"
    
    # CRITICAL: Use the SAME Python executable
    python_cmd = sys.executable
    
    # Get command line arguments (excluding the script name)
    # If you run "python 15m_bot_runner.py --live", this captures ['--live']
    bot_args = sys.argv[1:] if len(sys.argv) > 1 else []
    
    print("=" * 80)
    print("BTC 15-MIN TRADING BOT - AUTO-RESTART WRAPPER")
    print("=" * 80)
    print(f"Platform: {sys.platform}")
    print(f"Python: {python_cmd}")
    print(f"Bot script: {BOT_SCRIPT}")
    print(f"Bot arguments: {bot_args}")
    print(f"Virtual env: {sys.prefix}")
    print("=" * 80)
    print()
    
    # Check if bot script exists
    if not os.path.exists(BOT_SCRIPT):
        print(f"ERROR: Bot script '{BOT_SCRIPT}' not found!")
        print(f"Current directory: {os.getcwd()}")
        print(f"Files in directory: {os.listdir('.')}")
        print()
        print("Available .py files:")
        for file in os.listdir('.'):
            if file.endswith('.py'):
                print(f"  - {file}")
        print()
        print("Please set BOT_SCRIPT to your bot filename")
        sys.exit(1)
    
    restart_count = 0
    
    while True:
        restart_count += 1
        
        print("=" * 80)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
        print(f"Starting bot (restart #{restart_count})...")
        print(f"Command: {python_cmd} {BOT_SCRIPT} {' '.join(bot_args)}")
        print("=" * 80)
        print()
        
        try:
            # Run the bot with arguments!
            cmd = [python_cmd, BOT_SCRIPT] + bot_args
            result = subprocess.run(
                cmd,
                check=False
            )
            
            exit_code = result.returncode
            
            print()
            print("=" * 80)
            print(f"Bot stopped at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Exit code: {exit_code}")
            print("=" * 80)
            
            # Normal termination (auto-restart from bot)
            if exit_code in [0, 143, 15, -15]:
                print("✅ Normal auto-restart - loading fresh filters...")
                wait_time = 2
            else:
                print(f"⚠️ Error detected (code {exit_code}) - waiting before retry...")
                wait_time = 10
            
            print(f"Restarting in {wait_time} seconds...")
            print()
            time.sleep(wait_time)
            
        except KeyboardInterrupt:
            print()
            print("=" * 80)
            print("Keyboard interrupt received - stopping wrapper")
            print("=" * 80)
            break
            
        except Exception as e:
            print()
            print("=" * 80)
            print(f"ERROR running bot: {e}")
            print("=" * 80)
            print("Waiting 10 seconds before retry...")
            print()
            time.sleep(10)

if __name__ == "__main__":
    try:
        run_bot()
    except KeyboardInterrupt:
        print("\nStopped by user")
        sys.exit(0)