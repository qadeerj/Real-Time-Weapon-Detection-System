import argparse
from ultralytics import YOLO
import torch
import os

print("✅ GPU Available:", torch.cuda.is_available())
print("🔍 GPU Name:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "No GPU")

def main():
    parser = argparse.ArgumentParser(description="Train YOLOv8 model for weapon detection")
    parser.add_argument('--data', type=str, default='data.yaml', help='Path to data.yaml')
    parser.add_argument('--weights', type=str, default='yolov8m.pt', help='Base model weights (.pt)')
    parser.add_argument('--output', type=str, default='weights/', help='Output directory for trained weights')
    parser.add_argument('--epochs', type=int, default=100, help='Number of epochs')
    parser.add_argument('--batch', type=int, default=16, help='Batch size')
    parser.add_argument('--imgsz', type=int, default=960, help='Image size')
    parser.add_argument('--device', type=str, default='0', help='CUDA device')
    args = parser.parse_args()

    print(f"[INFO] Training with data: {args.data}")
    print(f"[INFO] Using weights: {args.weights}")
    print(f"[INFO] Output directory: {args.output}")
    print(f"[INFO] Epochs: {args.epochs}, Batch: {args.batch}, Image size: {args.imgsz}")

    # Ensure output directory exists
    os.makedirs(args.output, exist_ok=True)

    # Load YOLO model
    model = YOLO(args.weights)

    # Train
    results = model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=args.output,
        name='exp_weapon_yolov8',
        exist_ok=True,
        patience=10,
        val=False
    )
    print("[INFO] Training complete.")
    print(f"[INFO] Best weights saved to: {results.save_dir}")

if __name__ == '__main__':
    main()
