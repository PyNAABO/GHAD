# GitHub Action Downloader

Automate file downloads (torrents & direct links) using GitHub Actions and upload them to cloud storage via Rclone.

## 🚀 Features

- **Automated Downloads**: Triggers on push to `downloads.txt`.
- **Multi-Protocol Support**: Handles HTTP/HTTPS direct links and Torrents/Magnets via `aria2c`.
- **Cloud Upload**: Automatically uploads finished downloads to any Rclone-supported cloud storage (Google Drive, Mega, OneDrive, etc.).
- **Smart Processing**:
  - Retries failed downloads automatically.
  - Moves successful links to `completed.txt`.
  - Tracks failed links in `failed.txt`.
- **Secure**: Prevents argument injection and handles file operations safely.

## 🛠️ Setup

### 1. Configure Rclone Locally

Install Rclone on your machine and run `rclone config` to set up your remote storage. verify it works.
Get the content of your config file (usually `~/.config/rclone/rclone.conf` or `C:\Users\<User>\.config\rclone\rclone.conf`).

### 2. Add Secrets to GitHub

Go to **Settings > Secrets and variables > Actions** in your repository and add:

| Secret Name   | Value                                          |
| :------------ | :--------------------------------------------- |
| `RCLONE_CONF` | The entire content of your `rclone.conf` file. |

### 3. (Optional) Customize Remote Name

The script defaults to using a remote named `remote`. If your remote in `rclone.conf` has a different name (e.g., `mega`, `gdrive`), set it as an Environment Variable in `.github/workflows/main.yml`:

```yaml
env:
  RCLONE_REMOTE: mega
```

## 📦 Usage

1.  **Add Links**: Open `downloads.txt` and paste your links (one per line).
    ```text
    https://example.com/file.zip
    magnet:?xt=urn:btih:EXAMPLE...
    ```
2.  **Commit & Push**:
    ```bash
    git add downloads.txt
    git commit -m "Add new downloads"
    git push
    ```
3.  **Monitor**: Go to the **Actions** tab to see progress.
4.  **Result**:
    - Files uploaded to your cloud storage.
    - `downloads.txt` cleared.
    - `completed.txt` updated.

## ⚠️ Notes

- **Torrents**: Seeding is disabled (`--seed-time=0`) to save resources.
- **Large Files**: GitHub Actions has storage limits (~14GB disk space). For larger files, consider using a self-hosted runner.
