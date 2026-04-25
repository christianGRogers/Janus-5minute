# GitHub Actions Deployment Setup

## Overview

This project includes a GitHub Actions workflow that automatically builds a standalone executable whenever you push to the `main` branch. The executable can be downloaded and run on any server with environment variables configured via GitHub Secrets.

## Setting Up GitHub Secrets

To use the automated build and deployment, you need to configure GitHub Secrets with your environment variables.

### Step 1: Go to Repository Settings

1. Navigate to your repository: `https://github.com/christianGRogers/Janus-5minute`
2. Click on **Settings** (top right)
3. In the left sidebar, click **Secrets and variables** → **Actions**

### Step 2: Add Required Secrets

Click **New repository secret** and add the following:

#### Required Secrets:

| Secret Name | Value | Example |
|-------------|-------|---------|
| `POLYMARKET_API_KEY` | Your Polymarket API key | `pk_123abc...` |
| `POLYMARKET_PRIVATE_KEY` | Your Polymarket private key | `0x123abc...` |

#### Optional Secrets:

| Secret Name | Value | Default |
|-------------|-------|---------|
| `MARKET_FETCH_INTERVAL_MS` | Market data fetch interval in milliseconds | `5000` |
| `PAPER_TRADING_ENABLED` | Enable paper trading mode (`true`/`false`) | `true` |

### Step 3: Verify Secrets Are Set

Go to **Settings** → **Secrets and variables** → **Actions** and confirm all secrets are listed.

---

## Running the Workflow

### Automatic Trigger
The workflow automatically runs when you push to `main`:
```bash
git add .
git commit -m "Your changes"
git push origin main
```

### Manual Trigger
You can manually trigger the workflow:
1. Go to **Actions** tab in your repository
2. Select **Build and Release** workflow
3. Click **Run workflow** button
4. Select the branch (main)
5. Click **Run workflow**

---

## Downloading the Executable

### Option 1: Download from Release Page

1. Go to **Releases** in your repository sidebar
2. Find the latest release (v{run_number}-{commit_hash})
3. Download the appropriate executable:
   - **Linux**: `janus-bot` (for Linux servers)
   - **macOS**: `janus-bot-darwin-amd64` or `janus-bot-darwin-arm64`
   - **Windows**: Files from the artifact (built on Linux but should work)

### Option 2: Download from Artifacts

1. Go to **Actions** tab
2. Click on the latest **Build and Release** workflow run
3. Scroll down to **Artifacts** section
4. Download:
   - `janus-bot-build` - Contains the main executable and helper files
   - `janus-bot-linux-amd64` - Linux executable
   - `janus-bot-darwin-amd64` - macOS Intel executable
   - `janus-bot-darwin-arm64` - macOS Apple Silicon executable

---

## Running on a Server

### Setup on Server

1. **Download the executable** and helper files to your server
2. **Create `.env` file** with your secrets:
   ```bash
   cat > janus-bot.env << 'EOF'
   POLYMARKET_API_KEY=your_api_key_here
   POLYMARKET_PRIVATE_KEY=your_private_key_here
   MARKET_FETCH_INTERVAL_MS=5000
   PAPER_TRADING_ENABLED=true
   EOF
   ```

3. **Make the executable runnable** (Linux/macOS):
   ```bash
   chmod +x janus-bot
   chmod +x start-janus-bot.sh
   ```

### Running the Bot

#### Linux/macOS:
```bash
./start-janus-bot.sh
```

Or manually with environment variables:
```bash
export $(cat janus-bot.env | xargs)
./janus-bot
```

#### Windows (PowerShell):
```powershell
.\start-janus-bot.ps1
```

Or manually:
```powershell
$env:POLYMARKET_API_KEY = "your_key"
$env:POLYMARKET_PRIVATE_KEY = "your_private_key"
.\janus-bot.exe
```

### Running in Background (Linux/macOS)

Using `nohup`:
```bash
nohup ./start-janus-bot.sh > janus-bot.log 2>&1 &
```

Using `screen`:
```bash
screen -S janus-bot -d -m ./start-janus-bot.sh
```

Using `systemd` (recommended):
Create `/etc/systemd/system/janus-bot.service`:
```ini
[Unit]
Description=Janus Bot Trading Service
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/bot
EnvironmentFile=/path/to/janus-bot.env
ExecStart=/path/to/janus-bot
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable janus-bot
sudo systemctl start janus-bot
sudo systemctl status janus-bot
```

---

## Workflow Outputs

The workflow produces:

### Main Executable
- **Location**: Available in Releases and Artifacts
- **Size**: ~15-20 MB (depends on dependencies)
- **Type**: Standalone binary, no Go runtime required

### Helper Scripts
- **start-janus-bot.sh** - Bash script to load .env and run bot (Linux/macOS)
- **start-janus-bot.ps1** - PowerShell script to load .env and run bot (Windows)

### Documentation
- **.env.example** - Template for environment configuration
- **README.md** - Project documentation

---

## Troubleshooting

### Workflow Fails to Build
- Check that `go.mod` and `go.sum` are up to date
- Run locally: `go mod tidy && go build -o janus-bot ./cmd/bot`

### Executable Won't Start
- Verify environment variables are set: `echo $POLYMARKET_API_KEY`
- Check permissions: `ls -la janus-bot` (should show `x` flag)
- Run with debug: `./janus-bot -v` or check logs

### Environment Variables Not Loading
- **Linux/macOS**: Ensure `.env` file is in the same directory as executable
- **Windows**: Use the `.ps1` script or manually set variables before running
- Verify no trailing spaces in `.env` file

### Cross-Platform Issues
- Windows executables must have `.exe` extension (handled automatically)
- Linux executables need execute permissions: `chmod +x janus-bot`
- macOS might require removing quarantine: `xattr -d com.apple.quarantine janus-bot`

---

## Security Best Practices

1. **Never commit secrets** to the repository
2. **Use GitHub Secrets** for sensitive data (API keys, private keys)
3. **Restrict secret access** to necessary workflows only
4. **Rotate secrets periodically** for security
5. **Use read-only API keys** if available from Polymarket
6. **Secure the server** where the bot runs:
   - Use firewall rules
   - Limit SSH access
   - Enable monitoring and logging
   - Use VPN if accessing remotely

---

## CI/CD Pipeline Summary

```
Push to main
    ↓
Build Executable (Linux/macOS/Windows)
    ↓
Create .env file with GitHub Secrets
    ↓
Create startup scripts
    ↓
Create GitHub Release
    ↓
Upload Artifacts (30-day retention)
    ↓
Available for Download
```
