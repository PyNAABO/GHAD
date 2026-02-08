#!/bin/bash

DOWNLOAD_FILE="downloads.txt"
COMPLETED_FILE="completed.txt"
FAILED_FILE="failed.txt"
DOWNLOAD_DIR="downloads"
PROCESSING_FILE="processing.txt"

# Create download directory if it doesn't exist
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
    # Skip empty lines
    if [ -z "$link" ]; then
        continue
    fi

    echo "Processing: $link"

    # Download using aria2c
    # --seed-time=0: Stop seeding immediately
    # -x8 -s8: 8 connections (polite)
    # -k1M: 1MB chunks
    # --: End of options, prevents argument injection
    aria2c --seed-time=0 -x8 -s8 -k1M --dir="$DOWNLOAD_DIR" -- "$link"

    if [ $? -eq 0 ]; then
        echo "Download successful."

        # Upload to rclone remote
        # Default to 'remote' if not set
        RCLONE_REMOTE=${RCLONE_REMOTE:-remote}
        
        if ! rclone listremotes | grep -q "^${RCLONE_REMOTE}:"; then
             echo "Warning: Remote '${RCLONE_REMOTE}' not found in configuration."
        fi

        echo "Uploading to $RCLONE_REMOTE..."
        rclone copy "$DOWNLOAD_DIR" "$RCLONE_REMOTE:" -v

        if [ $? -eq 0 ]; then
            echo "Upload successful."
            # Append to completed file
            echo "$link" >> "$COMPLETED_FILE"
            
            # Clean up downloaded files safely
            if [ -d "$DOWNLOAD_DIR" ] && [ -n "$DOWNLOAD_DIR" ]; then
                find "$DOWNLOAD_DIR" -mindepth 1 -delete
            fi
        else
            echo "Upload failed for $link"
            echo "$link" >> "$FAILED_FILE"
            # Add back to downloads.txt for retry
            echo "$link" >> "$DOWNLOAD_FILE"
            
            # Clean up partial downloads safely
            if [ -d "$DOWNLOAD_DIR" ] && [ -n "$DOWNLOAD_DIR" ]; then
                find "$DOWNLOAD_DIR" -mindepth 1 -delete
            fi
        fi
    else
        echo "Download failed for $link"
        echo "$link" >> "$FAILED_FILE"
        # Add back to downloads.txt for retry
        echo "$link" >> "$DOWNLOAD_FILE"
        
        # Clean up partial downloads safely
        if [ -d "$DOWNLOAD_DIR" ] && [ -n "$DOWNLOAD_DIR" ]; then
            find "$DOWNLOAD_DIR" -mindepth 1 -delete
        fi
    fi

done < "$PROCESSING_FILE"

# Remove the processing file
rm "$PROCESSING_FILE"
