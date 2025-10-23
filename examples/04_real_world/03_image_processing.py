"""
Image Processing Pipeline: Parallel Media Processing

This example demonstrates parallel image processing pipelines that can handle
multiple images concurrently. Image processing is essential for content
creation, computer vision, and media workflows.

Processing Chain:
   Load → Resize → Apply Filter → Save
     ↓      ↓         ↓          ↓
  (Disk) (Scale)   (Enhance)   (Output)

Key Components:
- Load: Read images from various formats and sources
- Resize: Scale images to standard dimensions
- Filter: Apply effects like blur, sharpen, or color correction
- Save: Export processed images in desired formats

Real-world Use Cases:
- Photo editing workflows (batch resize and filter application)
- Computer vision preprocessing (standardize input images)
- Content delivery networks (generate multiple image sizes)
- Social media processing (create thumbnails and previews)
- Medical imaging (apply filters for better diagnosis)
- E-commerce (generate product image variants)

Queuack Features Demonstrated:
- Multiple independent DAGs for different images
- Sequential processing within each image pipeline
- Parallel execution across different images
- Job isolation and resource management
- Scalable batch processing patterns

Advanced Topics:
- Media processing: Handling different image formats
- Batch operations: Processing multiple files efficiently
- Resource optimization: Parallel processing for performance
- Quality control: Applying consistent transformations
- Storage management: Handling input/output file operations

# Difficulty: advanced
"""

import random
from datetime import datetime

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue

db_path = create_temp_path("images")
queue = DuckQueue(db_path)


def load_image(path: str):
    """Load image from disk or generate if doesn't exist."""
    import os

    # Use results directory for generated images
    results_dir = "results"
    os.makedirs(results_dir, exist_ok=True)
    full_path = os.path.join(results_dir, path)

    if not os.path.exists(full_path):
        print(f"📸 Generating sample image: {full_path}")
        # Generate a sample image if file doesn't exist
        img = Image.new(
            "RGB",
            (800, 600),
            color=(
                random.randint(0, 255),
                random.randint(0, 255),
                random.randint(0, 255),
            ),
        )

        # Add some shapes and text
        draw = ImageDraw.Draw(img)

        # Draw some random shapes
        for _ in range(10):
            x1, y1 = random.randint(0, 700), random.randint(0, 500)
            x2, y2 = x1 + random.randint(50, 100), y1 + random.randint(50, 100)
            color = (
                random.randint(0, 255),
                random.randint(0, 255),
                random.randint(0, 255),
            )
            draw.rectangle([x1, y1, x2, y2], fill=color, outline=color)

        # Add text
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32
            )
        except:
            font = ImageFont.load_default()

        draw.text(
            (50, 50), f"Sample Image: {os.path.basename(path)}", fill="white", font=font
        )
        draw.text(
            (50, 100),
            f"Generated at {datetime.now().strftime('%H:%M:%S')}",
            fill="white",
            font=font,
        )

        img.save(full_path)
        print(f"   Created {img.size[0]}x{img.size[1]} image")

    return Image.open(full_path)


def resize_image(input_path: str):
    """Resize image from file and save."""
    import os

    # Use results directory
    results_dir = "results"
    os.makedirs(results_dir, exist_ok=True)

    # Load image
    img = Image.open(os.path.join(results_dir, input_path))

    print(f"📏 Resizing image from {img.size} to (800, 600)")
    resized = img.resize((800, 600), Image.Resampling.LANCZOS)

    # Add resize metadata
    draw = ImageDraw.Draw(resized)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    except:
        font = ImageFont.load_default()

    draw.text((10, 10), "Resized to 800x600", fill="white", font=font)

    # Save resized image
    output_path = f"resized_{input_path}"
    full_output_path = os.path.join(results_dir, output_path)
    resized.save(full_output_path)
    print(f"✅ Saved resized {resized.size[0]}x{resized.size[1]} image")

    return output_path


def apply_filter(input_path: str, filter_type="BLUR"):
    """Apply image filter from file and save."""
    import os

    # Use results directory
    results_dir = "results"
    os.makedirs(results_dir, exist_ok=True)

    # Load image
    img = Image.open(os.path.join(results_dir, input_path))

    print(f"🎨 Applying {filter_type} filter")

    # Apply the filter
    filtered = img.filter(getattr(ImageFilter, filter_type))

    # Add filter metadata
    draw = ImageDraw.Draw(filtered)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    except:
        font = ImageFont.load_default()

    draw.text((10, 30), f"Filter: {filter_type}", fill="white", font=font)

    # Save filtered image
    output_path = f"filtered_{filter_type.lower()}_{input_path}"
    full_output_path = os.path.join(results_dir, output_path)
    filtered.save(full_output_path)
    print("✅ Saved filtered image")

    return output_path


def save_image(input_path: str, output_path: str):
    """Save processed image with metadata."""
    import os

    # Use results directory
    results_dir = "results"
    os.makedirs(results_dir, exist_ok=True)

    # Load the processed image
    img = Image.open(os.path.join(results_dir, input_path))

    print(f"💾 Saving processed image to {output_path}")

    # Add final processing timestamp
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    except:
        font = ImageFont.load_default()

    draw.text(
        (10, 50),
        f"Processed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        fill="white",
        font=font,
    )

    full_output_path = os.path.join(results_dir, output_path)
    img.save(full_output_path)
    print(f"✅ Saved {img.size[0]}x{img.size[1]} image ({full_output_path})")

    return full_output_path


# Process multiple images in parallel with different filters
image_files = ["landscape.jpg", "portrait.jpg", "abstract.jpg"]
filters = ["BLUR", "CONTOUR", "EMBOSS"]

for i, img_file in enumerate(image_files):
    with queue.dag(f"process_{img_file}") as dag:
        # Each job works with the same base filename
        load = dag.enqueue(load_image, args=(img_file,), name="load")
        resize = dag.enqueue(resize_image, args=(img_file,), name="resize")

        # Apply different filters to different images
        filter_type = filters[i % len(filters)]
        blur = dag.enqueue(
            apply_filter,
            args=(f"resized_{img_file}", filter_type),
            name=f"filter_{filter_type.lower()}",
        )

        save = dag.enqueue(
            save_image,
            args=(
                f"filtered_{filter_type.lower()}_resized_{img_file}",
                f"processed_{img_file}",
            ),
            name="save",
        )

# Execute the image processing jobs
print("\n🚀 Executing image processing jobs...")
import time

total_jobs = len(image_files) * 3  # 3 jobs per image (load, resize, filter, save)
processed = 0

while processed < total_jobs:
    job = queue.claim()
    if job:
        processed += 1
        print(f"📋 Processing job #{processed}: {job.id[:8]}")

        try:
            result = job.execute()
            queue.ack(job.id, result=result)
            print(f"✅ Completed job #{processed}")

        except Exception as e:
            queue.ack(job.id, error=str(e))
            print(f"❌ Failed job #{processed}: {e}")
    else:
        print("⏳ Waiting for jobs...")
        time.sleep(0.5)

print("\n🎉 Image processing complete!")

# List generated files
import os

print("\n📁 Generated files:")
results_dir = "results"
if os.path.exists(results_dir):
    image_count = 0
    for file in os.listdir(results_dir):
        if file.startswith("processed_") and file.endswith(".jpg"):
            print(f"   🖼️  {os.path.join(results_dir, file)}")
            image_count += 1
        elif file.endswith((".jpg", ".png")) and not file.startswith("processed_"):
            print(f"   📸 {os.path.join(results_dir, file)}")
            image_count += 1

    print(f"\n📊 Total images processed: {image_count}")
else:
    print("   No results directory found")
