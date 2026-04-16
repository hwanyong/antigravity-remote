import sys
try:
    from AppKit import NSPasteboard, NSPasteboardTypePNG, NSPasteboardTypeTIFF, NSPasteboardTypeFileURL
    pb = NSPasteboard.generalPasteboard()
    
    png_data = pb.dataForType_(NSPasteboardTypePNG)
    if png_data:
        print("Found PNG in clipboard. Size:", len(png_data))
        sys.exit(0)
        
    tiff_data = pb.dataForType_(NSPasteboardTypeTIFF)
    if tiff_data:
        print("Found TIFF in clipboard. Size:", len(tiff_data))
        sys.exit(0)
    
    file_url = pb.stringForType_(NSPasteboardTypeFileURL)
    if file_url:
        print("Found FileURL in clipboard:", file_url)
        sys.exit(0)
        
    print("No image or image file URL found in clipboard.")
except Exception as e:
    print(f"Error accessing clipboard: {e}")
