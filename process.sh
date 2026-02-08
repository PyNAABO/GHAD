#!/bin/bash

DOWNLOAD_FILE="downloads.txt"
COMPLETED_FILE="completed.txt"
FAILED_FILE="failed.txt"
DOWNLOAD_DIR="downloads"

# Create download directory if it doesn't exist
mkdir -p "$DOWNLOAD_DIR"

if [ ! -f "$DOWNLOAD_FILE" ]; then
    echo "$DOWNLOAD_FILE not found!"
    exit 0
fi

# Check if file is empty
if [ ! -s "$DOWNLOAD_FILE" ]; then
    echo "No downloads pending."
    exit 0
fi

# Process each line
while IFS= read -r link || [ -n "$link" ]; do
    # Skip empty lines
    if [ -z "$link" ]; then
        continue
    fi

    echo "Processing: $link"

    # Download using aria2c
    # --seed-time=0 ensures torrents stop seeding immediately after download
    # -x16 -s16: Use 16 connections/servers for faster downloads
    # -k1M: Use 1MB chunks
    aria2c --seed-time=0 -x16 -s16 -k1M --dir="$DOWNLOAD_DIR" "$link"

    if [ $? -eq 0 ]; then
        echo "Download successful."

        # Upload to rclone remote
    RCLONE_REMOTE=${RCLONE_REMOTE:-mega}
    echo "Uploading to $RCLONE_REMOTE..."
    rclone copy "$DOWNLOAD_DIR" "$RCLONE_REMOTE:" -v

    if [ $? -eq 0 ]; then
        echo "Upload successful."
        # Append to completed file
        echo "$link" >> "$COMPLETED_FILE"
        
        # Remove the processed link from downloads.txt
        # specific to the exact line match to avoid partial matches
        grep -Fxv "$link" "$DOWNLOAD_FILE" > "${DOWNLOAD_FILE}.tmp" && mv "${DOWNLOAD_FILE}.tmp" "$DOWNLOAD_FILE"

        # Clean up downloaded files
        rm -rf "$DOWNLOAD_DIR"/*
        else
            echo "Upload failed for $link"
        fi
    else
        echo "Download failed for $link"
        echo "$link" >> "$FAILED_FILE"
        
        # Remove the failed link from downloads.txt
        grep -Fxv "$link" "$DOWNLOAD_FILE" > "${DOWNLOAD_FILE}.tmp" && mv "${DOWNLOAD_FILE}.tmp" "$DOWNLOAD_FILE"
        
        # Clean up partial downloads if any
        rm -rf "$DOWNLOAD_DIR"/*
    fi

done < "$DOWNLOAD_FILE"
