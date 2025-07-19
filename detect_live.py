import cv2
from ultralytics import YOLO

# Class names as per data.yaml
class_names = ['handgun', 'rifel', 'shotgun', 'snipper']

# Set your input and output video file paths here
input_video_path = r'C:\Users\muham\Downloads\GunDetection-main\GunDetection-main\Sample\cc.mp4'
output_video_path = 'output02.mp4'

def main():
    # Load the trained YOLOv8 model
    model = YOLO('best')

    # Open the input video
    cap = cv2.VideoCapture(input_video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video file {input_video_path}")
        return

    # Get video properties
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_video_path, fourcc, fps, (width, height))

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Run YOLOv8 inference on the frame
        results = model(frame)

        # Visualize results
        for result in results:
            boxes = result.boxes
            for box in boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])
                cls = int(box.cls[0])
                label = f"{class_names[cls]} {conf:.2f}"
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        out.write(frame)
        cv2.imshow('Weapon Detection', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    out.release()
    cv2.destroyAllWindows()
    print(f"Annotated video saved to {output_video_path}")

if __name__ == '__main__':
    main() 