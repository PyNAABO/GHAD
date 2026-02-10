#!/bin/bash

DOWNLOAD_FILE="downloads.txt"
COMPLETED_FILE="completed.txt"
FAILED_FILE="failed.txt"
DOWNLOAD_DIR="downloads"
PROCESSING_FILE="processing.txt"

# Deduplicate failed.txt if it exists
if [ -f "$FAILED_FILE" ] && [ -s "$FAILED_FILE" ]; then
    awk '!seen[$0]++' "$FAILED_FILE" > "${FAILED_FILE}.tmp" && mv "${FAILED_FILE}.tmp" "$FAILED_FILE"
fi
mkdir -p "$DOWNLOAD_DIR"

if [ ! -f "$DOWNLOAD_FILE" ] || [ ! -s "$DOWNLOAD_FILE" ]; then
    echo "No downloads pending."
    exit 0
fi

# Move downloads to a temporary processing file to avoid race conditions
mv "$DOWNLOAD_FILE" "$PROCESSING_FILE"
touch "$DOWNLOAD_FILE"

# Check if URL is a direct video file (not a webpage)
is_direct_video() {
    local url="$1"
    [[ "$url" =~ \.(mp4|mkv|webm|avi|mov|flv|wmv|m4v|3gp|flac|mkv)$ ]] || \
    [[ "$url" =~ /video/ ]] || \
    [[ "$url" =~ /get_file/ ]] || \
    [[ "$url" =~ /download/ ]] || \
    [[ "$url" =~ \.mp4\? ]] || \
    [[ "$url" =~ \.m3u8 ]]
}

# Process each line
while IFS= read -r link || [ -n "$link" ]; do
    # Skip empty lines and strip carriage returns (handle Windows line endings)
    link=$(echo "$link" | tr -d '\r')
    if [ -z "$link" ]; then
        continue
    fi

    echo "========================================"
    echo "Processing: $link"
    echo "========================================"

    DOWNLOAD_SUCCESS=false
    IS_WEBPAGE=false

    # Check if this is a webpage (not a direct video file)
    if ! is_direct_video "$link"; then
        IS_WEBPAGE=true
        echo "[INFO] Webpage URL detected - using page extraction"
    fi

    # Method 1: yt-dlp first with Cloudflare impersonation
    if command -v yt-dlp &> /dev/null; then
        echo "[1/3] Trying yt-dlp with Cloudflare bypass..."

        if [ "$IS_WEBPAGE" = true ]; then
            # Try with impersonation first
            yt-dlp --extractor-args "generic:impersonate" -o "$DOWNLOAD_DIR/%(title)s.%(ext)s" -- "$link" 2>&1
        else
            yt-dlp -o "$DOWNLOAD_DIR/%(title)s.%(ext)s" -- "$link" 2>&1
        fi

        if [ $? -eq 0 ]; then
            echo "[✓] yt-dlp succeeded"
            DOWNLOAD_SUCCESS=true
        else
            # Retry with cookies if available
            if [ -f "cookies.txt" ]; then
                echo "[Retry] Trying with cookies..."
                yt-dlp --cookies cookies.txt -o "$DOWNLOAD_DIR/%(title)s.%(ext)s" -- "$link" 2>&1
                if [ $? -eq 0 ]; then
                    echo "[✓] yt-dlp with cookies succeeded"
                    DOWNLOAD_SUCCESS=true
                fi
            fi
        fi
    fi

    # Method 2: aria2c ONLY for direct video files (not webpages)
    if [ "$DOWNLOAD_SUCCESS" = false ] && [ "$IS_WEBPAGE" = false ]; then
        echo "[2/3] Trying aria2c (direct video link)..."
        aria2c --seed-time=0 -x8 -s8 -k1M --dir="$DOWNLOAD_DIR" -- "$link" 2>&1
        if [ $? -eq 0 ]; then
            echo "[✓] aria2c succeeded"
            DOWNLOAD_SUCCESS=true
        else
            echo "[✗] aria2c failed"
        fi
    elif [ "$IS_WEBPAGE" = true ]; then
        echo "[2/3] Skipping aria2c (not a direct video link)"
    fi

    # Method 3: Browser fallback for webpages that yt-dlp couldn't handle
    if [ "$DOWNLOAD_SUCCESS" = false ] && [ "$IS_WEBPAGE" = true ] && [ -f "browser_download.py" ]; then
        echo "[3/3] Trying browser download..."
        FILENAME=$(echo "$link" | md5sum | cut -c1-16).mp4
        if [ -f "cookies.txt" ]; then
            python3 browser_download.py "$link" "$FILENAME" "cookies.txt" 2>&1
        else
            python3 browser_download.py "$link" "$FILENAME" 2>&1
        fi
        if [ $? -eq 0 ] && [ -f "$DOWNLOAD_DIR/$FILENAME" ]; then
            echo "[✓] Browser download succeeded"
            DOWNLOAD_SUCCESS=true
        else
            echo "[✗] Browser download failed"
        fi
    fi

    # Handle result
    if [ "$DOWNLOAD_SUCCESS" = true ]; then
        echo "Download successful."

        # Upload to rclone remote
        RCLONE_REMOTE=${RCLONE_REMOTE:-remote}

        if ! rclone listremotes | grep -q "^${RCLONE_REMOTE}:"; then
             echo "Warning: Remote '${RCLONE_REMOTE}' not found in configuration."
        fi

        echo "Uploading to $RCLONE_REMOTE..."
        rclone copy "$DOWNLOAD_DIR" "$RCLONE_REMOTE:" -v

        if [ $? -eq 0 ]; then
            echo "Upload successful."
            echo "$link" >> "$COMPLETED_FILE"

            # Clean up downloaded files
            if [ -d "$DOWNLOAD_DIR" ] && [ -n "$DOWNLOAD_DIR" ]; then
                find "$DOWNLOAD_DIR" -mindepth 1 -delete
            fi
        else
            echo "Upload failed for $link"
            echo "$link" >> "$FAILED_FILE"
            if [ -d "$DOWNLOAD_DIR" ] && [ -n "$DOWNLOAD_DIR" ]; then
                find "$DOWNLOAD_DIR" -mindepth 1 -delete
            fi
        fi
    else
        echo "Download FAILED for $link"
        echo "$link" >> "$FAILED_FILE"

        if [ -d "$DOWNLOAD_DIR" ] && [ -n "$DOWNLOAD_DIR" ]; then
            find "$DOWNLOAD_DIR" -mindepth 1 -delete
        fi
    fi

done < "$PROCESSING_FILE"

# Remove the processing file
rm "$PROCESSING_FILE"

echo "Done!"
