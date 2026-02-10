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

    # Method 1: Try yt-dlp first (supports 1000+ sites)
    if command -v yt-dlp &> /dev/null; then
        echo "[1/3] Trying yt-dlp..."
        yt-dlp --no-playlist -o "$DOWNLOAD_DIR/%(title)s.%(ext)s" -- "$link" 2>&1
        if [ $? -eq 0 ]; then
            echo "[✓] yt-dlp succeeded"
            DOWNLOAD_SUCCESS=true
        else
            echo "[✗] yt-dlp failed"
        fi
    fi

    # Method 2: Try aria2c if yt-dlp didn't succeed
    if [ "$DOWNLOAD_SUCCESS" = false ]; then
        echo "[2/3] Trying aria2c..."
        aria2c --seed-time=0 -x8 -s8 -k1M --dir="$DOWNLOAD_DIR" -- "$link" 2>&1
        if [ $? -eq 0 ]; then
            echo "[✓] aria2c succeeded"
            DOWNLOAD_SUCCESS=true
        else
            echo "[✗] aria2c failed"
        fi
    fi

    # Method 3: Try browser download as last resort (requires Playwright)
    if [ "$DOWNLOAD_SUCCESS" = false ] && [ -f "browser_download.py" ]; then
        echo "[3/3] Trying browser download..."
        FILENAME=$(echo "$link" | md5sum | cut -c1-16).mp4
        python3 browser_download.py "$link" "$FILENAME" 2>&1
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
