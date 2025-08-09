#!/usr/bin/env python3
"""
Railway Pre-deployment Setup Script
This script checks for required environment variables before starting the bot.
Place this in your repository and update your Dockerfile to use it.
"""

import os
import sys
import time
from typing import Dict, List, Optional

# Required environment variables
REQUIRED_VARS = {
    'API_ID': 'Telegram API ID from my.telegram.org',
    'API_HASH': 'Telegram API Hash from my.telegram.org',
    'BOT_TOKEN': 'Bot token from @BotFather',
    'DATABASE_URI': 'MongoDB connection string',
    'REDIS_URI': 'Redis connection string',
    'ADMINS': 'Admin user IDs (comma separated)',
    'LOG_CHANNEL': 'Channel ID for bot logs'
}

# Optional but recommended variables
OPTIONAL_VARS = {
    'CHANNELS': 'Channels to auto-index (comma separated)',
    'AUTH_CHANNEL': 'Force subscription channel ID',
    'SUPPORT_GROUP_ID': 'Support group ID',
    'FILE_STORE_CHANNEL': 'File store channels'
}


def print_banner():
    """Print setup banner"""
    print("=" * 60)
    print("🚀 RAILWAY TELEGRAM BOT DEPLOYMENT SETUP")
    print("=" * 60)
    print()


def check_railway_services():
    """Check if Railway services are available"""
    print("📡 Checking Railway services...")

    # Check MongoDB
    mongo_url = os.getenv('MONGO_URL')
    mongodb_url = os.getenv('DATABASE_URI')

    if mongo_url and not mongodb_url:
        os.environ['DATABASE_URI'] = mongo_url
        print("✅ MongoDB service detected and configured")
    elif mongodb_url:
        print("✅ MongoDB connection configured")
    else:
        print("❌ MongoDB not configured")
        return False

    # Check Redis
    redis_url = os.getenv('REDIS_URL')
    redis_uri = os.getenv('REDIS_URI')

    if redis_url and not redis_uri:
        os.environ['REDIS_URI'] = redis_url
        print("✅ Redis service detected and configured")
    elif redis_uri:
        print("✅ Redis connection configured")
    else:
        print("❌ Redis not configured")
        return False

    return True


def check_required_vars() -> Dict[str, Optional[str]]:
    """Check for required environment variables"""
    print("\n🔍 Checking required environment variables...")

    missing_vars = {}
    configured_vars = {}

    for var, description in REQUIRED_VARS.items():
        value = os.getenv(var)
        if not value or value.strip() == '':
            missing_vars[var] = description
            print(f"❌ {var}: Not set - {description}")
        else:
            configured_vars[var] = value
            # Don't print sensitive values
            if var in ['BOT_TOKEN', 'API_HASH']:
                print(f"✅ {var}: Configured (hidden)")
            else:
                print(f"✅ {var}: {value}")

    return missing_vars


def check_optional_vars():
    """Check for optional environment variables"""
    print("\n🔧 Checking optional environment variables...")

    for var, description in OPTIONAL_VARS.items():
        value = os.getenv(var)
        if value and value.strip():
            print(f"✅ {var}: {value}")
        else:
            print(f"⚪ {var}: Not set - {description}")


def print_setup_instructions(missing_vars: Dict[str, str]):
    """Print setup instructions for missing variables"""
    if not missing_vars:
        return

    print("\n" + "=" * 60)
    print("📋 SETUP INSTRUCTIONS")
    print("=" * 60)
    print("\n🚨 Missing Required Variables:")
    print("\nTo fix this, go to your Railway dashboard:")
    print("1. Open your project")
    print("2. Click on your bot service")
    print("3. Go to 'Variables' tab")
    print("4. Add these variables:\n")

    for var, description in missing_vars.items():
        print(f"   {var}")
        print(f"   └── {description}")

        # Add specific instructions for each variable
        if var == 'API_ID' or var == 'API_HASH':
            print("   └── Get from: https://my.telegram.org")
        elif var == 'BOT_TOKEN':
            print("   └── Get from: @BotFather on Telegram")
        elif var == 'ADMINS':
            print("   └── Get your ID from: @userinfobot on Telegram")
        elif var == 'LOG_CHANNEL':
            print("   └── Create a channel and add your bot as admin")
        elif var == 'DATABASE_URI':
            print("   └── Add MongoDB service: ${{MongoDB.MONGO_URL}}")
        elif var == 'REDIS_URI':
            print("   └── Add Redis service: ${{Redis.REDIS_URL}}")
        print()

    print("5. After adding variables, go to 'Deployments' tab")
    print("6. Click 'Deploy Latest' to restart with new config")
    print("\n📚 Full guide: https://github.com/rumalg123/Advanced-File-Filter-Bot#railway-deployment")


def wait_for_configuration():
    """Wait for user to configure variables"""
    print("\n⏳ Waiting for configuration...")
    print("This service will check every 30 seconds for required variables.")
    print("Configure the variables in Railway dashboard and the bot will start automatically.")
    print("\nPress Ctrl+C to stop waiting and exit.")

    attempt = 1
    while True:
        try:
            print(f"\n🔄 Check #{attempt} - {time.strftime('%Y-%m-%d %H:%M:%S')}")

            # Re-check services (in case they were just added)
            if not check_railway_services():
                print("❌ Railway services not ready yet...")
                time.sleep(30)
                attempt += 1
                continue

            # Re-check variables
            missing = check_required_vars()
            if not missing:
                print("\n🎉 All required variables configured!")
                return True

            print(f"⏸️  Still missing {len(missing)} variables...")
            time.sleep(30)
            attempt += 1

        except KeyboardInterrupt:
            print("\n\n👋 Setup cancelled by user")
            return False


def main():
    """Main setup function"""
    print_banner()

    # Check Railway services first
    if not check_railway_services():
        print("\n❌ Railway services not configured properly")
        print("\nPlease add MongoDB and Redis services to your Railway project:")
        print("1. Go to your Railway project dashboard")
        print("2. Click 'New' → 'Database' → 'Add MongoDB'")
        print("3. Click 'New' → 'Database' → 'Add Redis'")
        print("4. Wait for services to deploy")
        print("5. Redeploy this service")
        sys.exit(1)

    # Check required variables
    missing_vars = check_required_vars()
    check_optional_vars()

    if missing_vars:
        print_setup_instructions(missing_vars)

        # In Railway, wait for configuration instead of exiting
        if os.getenv('RAILWAY_ENVIRONMENT_NAME'):
            if not wait_for_configuration():
                sys.exit(1)
        else:
            print(f"\n❌ Missing {len(missing_vars)} required variables")
            sys.exit(1)

    print("\n🎉 Configuration complete!")
    print("🚀 Starting Telegram bot...")
    print("=" * 60)

    # Import and start the bot
    try:
        import bot
        # The bot module will handle the rest
    except ImportError as e:
        print(f"❌ Error importing bot module: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error starting bot: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()