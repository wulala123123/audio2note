# filename: backend/crop_ppt.py
import cv2
import tqdm
from pathlib import Path

def locate_ppt_and_save_debug_images(frame, debug_image_dir: Path):
    """
    在单帧中定位PPT区域，并保存所有中间调试步骤的图像。
    
    参数:
        frame: 视频中的一帧图像 (numpy array)
        debug_image_dir: 保存调试图片的文件夹 (Path object)
    返回:
        如果找到，则返回包含 (x, y, w, h) 的元组，否则返回 None.
    """
    print("--- 开始定位并生成调试图片 ---")
    
    # 0. 保存原始帧
    cv2.imwrite(str(debug_image_dir / "0_original_frame.jpg"), frame)
    print(f"  -> 已保存 '0_original_frame.jpg' 到 {debug_image_dir}")

    # 1. 预处理：灰度图
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    cv2.imwrite(str(debug_image_dir / "1_grayscale.jpg"), gray)
    print(f"  -> 已保存 '1_grayscale.jpg' 到 {debug_image_dir}")
    
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    
    # 2. 边缘检测
    edged = cv2.Canny(blurred, 30, 120)
    cv2.imwrite(str(debug_image_dir / "2_canny_edges.jpg"), edged)
    print(f"  -> 已保存 '2_canny_edges.jpg' 到 {debug_image_dir}")

    # 3. 寻找并绘制所有轮廓
    contours, _ = cv2.findContours(edged.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours_debug_image = frame.copy()
    cv2.drawContours(contours_debug_image, contours, -1, (0, 0, 255), 2) # 红色
    cv2.imwrite(str(debug_image_dir / "3_all_contours_found.jpg"), contours_debug_image)
    print(f"  -> 已保存 '3_all_contours_found.jpg' 到 {debug_image_dir}")
    
    if not contours:
        print("--- 未找到任何轮廓 ---")
        return None

    # 4. 筛选轮廓并找到最终目标
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]
    for c in contours:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.03 * peri, True)

        if len(approx) == 4 and cv2.contourArea(c) > frame.shape[0] * frame.shape[1] * 0.1:
            # 找到了！绘制最终结果
            final_result_image = frame.copy()
            cv2.drawContours(final_result_image, [approx], -1, (0, 255, 0), 3) # 绿色
            cv2.imwrite(str(debug_image_dir / "4_final_result.jpg"), final_result_image)
            print(f"  -> 已保存 '4_final_result.jpg' 到 {debug_image_dir}")
            print("--- 调试图片生成完毕 ---")
            return cv2.boundingRect(approx)
            
    print("--- 未能找到符合条件的PPT区域 ---")
    return None

def process_video(input_video_path: Path, output_base_dir: Path) -> Path | None:
    """
    处理单个视频文件：定位、裁剪并保存。
    
    Args:
        input_video_path: 输入视频的完整路径
        output_base_dir: 输出的基础目录 (包含 'video' 和 'image' 子目录)
    
    Returns:
        成功则返回剪裁后的视频路径，失败返回 None
    """
    input_video_path = Path(input_video_path)
    output_base_dir = Path(output_base_dir)
    
    print(f"\n{'='*20} 开始处理视频: {input_video_path.name} {'='*20}")
    
    # 1. 配置路径
    video_name = input_video_path.stem
    output_video_dir = output_base_dir / 'video' / video_name
    output_video_path = output_video_dir / f"{video_name}_cropped.mp4"
    output_debug_image_dir = output_base_dir / 'image' / video_name
    
    # 2. 检查是否已处理过
    if output_video_dir.exists():
        print(f"跳过: 输出目录 '{output_video_dir}' 已存在。")
        return output_video_path

    output_video_dir.mkdir(parents=True, exist_ok=True)
    output_debug_image_dir.mkdir(parents=True, exist_ok=True)
    
    # 3. 打开视频
    cap = cv2.VideoCapture(str(input_video_path))
    if not cap.isOpened():
        print(f"错误：无法打开视频文件 '{input_video_path}'。")
        return None

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    # 4. 多次尝试定位PPT区域
    bbox = None
    sample_points = [1/5, 2/5, 3/5] # 尝试视频的三个不同位置
    for i, point in enumerate(sample_points):
        print(f"\n第 {i+1}/{len(sample_points)} 次尝试: 正在读取视频 {point*100:.0f}% 处的样本帧...")
        frame_number_to_read = int(total_frames * point)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number_to_read)
        ret, sample_frame = cap.read()
        if not ret:
            print(f"警告：无法读取第 {frame_number_to_read} 帧。")
            continue
        
        # 执行定位和调试图片生成
        bbox = locate_ppt_and_save_debug_images(sample_frame, output_debug_image_dir)
        if bbox:
            print(f"成功在视频 {point*100:.0f}% 处定位到PPT！")
            break # 找到就跳出循环

    if not bbox:
        print(f"\n错误：在 '{input_video_path.name}' 中多次尝试后仍自动定位失败。请检查调试图片。")
        cap.release()
        return None

    x, y, w, h = bbox
    print(f"\n成功定位PPT区域！将使用固定坐标进行剪裁: x={x}, y={y}, 宽={w}, 高={h}")

    # 5. 初始化视频写入器
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(str(output_video_path), fourcc, fps, (w, h))

    # 6. 高速逐帧剪裁
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0) # 重置到视频开头
    print("开始使用固定坐标进行高速剪裁...")
    
    with tqdm.tqdm(total=total_frames, desc=f"剪裁 {video_name}") as pbar:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            cropped_frame = frame[y:y+h, x:x+w]
            writer.write(cropped_frame)
            pbar.update(1)

    # 7. 清理和收尾
    print("\n处理完成！")
    cap.release()
    writer.release()
    print(f"成功生成剪裁后的视频，文件路径: {output_video_path}")
    print(f"调试图片已保存在: {output_debug_image_dir}")
    
    return output_video_path

def main():
    """主执行函数，用于查找并处理所有输入视频。"""
    # 自动定位项目根目录（假设 backend 是根目录的直接子目录）
    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parent
    
    input_dir = project_root / 'input'
    output_dir = project_root / 'output'
    
    # 支持多种视频格式
    video_extensions = ['*.mp4', '*.m4s', '*.avi', '*.mov', '*.mkv']
    input_video_paths = []
    
    if not input_dir.exists():
        input_dir.mkdir(parents=True)
        print(f"已创建 '{input_dir}' 文件夹，请将视频文件放入其中。")
        return

    for ext in video_extensions:
        input_video_paths.extend(input_dir.glob(ext))
    
    if not input_video_paths:
        print(f"错误: 在 '{input_dir}' 文件夹中没有找到任何视频文件。")
        return

    print(f"在 '{input_dir}' 文件夹中找到 {len(input_video_paths)} 个视频文件。")
    
    # 2. 循环处理每个视频
    for video_path in input_video_paths:
        process_video(video_path, output_dir)

    print(f"\n{'='*25} 所有视频裁剪完毕 {'='*25}")


if __name__ == "__main__":
    main()