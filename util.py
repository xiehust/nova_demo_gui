from json import JSONDecodeError
import base64
import io
import os
import json
import logging
import time
import re
import json
import magic
import random
import string
from datetime import datetime
from moviepy import VideoFileClip, CompositeVideoClip
from moviepy import TextClip
import cv2
import base64
import boto3
from botocore.config import Config
from PIL import Image
import qrcode
from botocore.exceptions import NoCredentialsError


PRO_MODEL_ID = "us.amazon.nova-pro-v1:0"
LITE_MODEL_ID = "us.amazon.nova-lite-v1:0"
MICRO_MODEL_ID = "us.amazon.nova-micro-v1:0"

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

system_sequnce = \
"""
我需要你帮我把以下场景描述拆分成一系列连续的镜头。每个镜头都应该：
1. 包含一个清晰的画面重点
2. 描述具体的视觉元素(如构图、光线、视角等)
3. 适合用于AI图像生成
4. 使用简洁的英文描述
5. 添加关键的艺术风格和氛围标签
6. 当前镜头要考虑和上一个镜头的连贯性
7. 镜头分为前序，主体和结尾3个

#注意事项
- Prompting for image generation models differs from prompting for large language models (LLMs). Image generation models do not have the ability to reason or interpret explicit commands. Therefore, it's best to phrase your prompt as if it were an image caption rather than a command or conversation.
- Consider adding modifiers like aspect ratios, image quality settings, or post-processing instructions to refine the output.
- Avoid topics such as pornography, racial discrimination, and toxic words.
- Do not use negation words like "no", "not", "without", and so on in your prompt. The model doesn't understand negation in a prompt and attempting to use negation will result in the opposite of what you intend. For example, a prompt such as "a fruit basket with no bananas" will actually signal the model to include bananas. Instead, you can use a negative prompt, via the negative prompt, to specify any objects or characteristics that you want to exclude from the image. For example "bananas".

请将以下场景描述拆分为分镜，并以精简的 JSON 格式输出：
{
    "shots": [
        {
            "id": "shot_1",
            "description": "场景描述",
            "composition": "构图说明",
            "lighting": "光线说明",
            "angle": "视角说明",
            "distance": "景别说明",
            "style_tags": ["标签1", "标签2", "标签3"],
            "prompt": "英文提示词",
            "negative_prompt": "(可选)负向提示词"
        }
    ]
}


##示例##
场景描述：一个女孩在黄昏时分走在海边的沙滩上，远处是落日和帆船。

输出：
{
    "shots": [
        {
            "id": "shot_1",
            "description": "远景镜头，展现黄昏海滩的整体氛围",
            "composition": "wide angle composition",
            "lighting": "natural sunset lighting",
            "angle": "eye level",
            "distance": "long shot",
            "style_tags": ["cinematic", "golden hour", "peaceful", "warm colors"],
            "prompt": "wide shot of a beach at sunset, golden hour, sailing boats on horizon, cinematic lighting",
            "negative_prompt":""
        },
        {
            "id": "shot_2",
            "description": "女孩的背影剪影",
            "composition": "rule of thirds",
            "lighting": "backlight",
            "angle": "side view",
            "distance": "medium shot",
            "style_tags": ["atmospheric", "moody", "dramatic", "silhouette"],
            "prompt": "silhouette of a girl walking on beach, sunset backdrop, side view, dramatic lighting",
            "negative_prompt":"wrong leg"
        },
        {
            "id": "shot_3",
            "description": "特写镜头展现女孩的表情和周围环境细节",
            "composition": "centered composition",
            "lighting": "side lighting",
            "angle": "eye level",
            "distance": "close-up",
            "style_tags": ["portrait", "emotional", "soft lighting", "intimate"],
            "prompt": "close-up shot of a girl's face, warm sunset light, beach background, soft focus",
            "negative_prompt":""
        }
    ]
}
"""

system_division_3 = """
You are a screenwriter, and I need your help to rewrite and expand the input to a story and then break down the following scene description into a series of storyboard shots. Each shot should:
- Include a clear focal point
- Use concise English descriptions
- Contain <num_shot> shots

## Notes
- Prompting for image generation models differs from prompting for large language models (LLMs). Image generation models do not have the ability to reason or interpret explicit commands. Therefore, it's best to phrase your prompt as if it were an image caption rather than a command or conversation.
- Consider adding modifiers like aspect ratios, image quality settings, or post-processing instructions to refine the output.
- Avoid topics such as pornography, racial discrimination, and toxic words.
- Do not use negation words like "no", "not", "without", and so on in your prompt. The model doesn't understand negation in a prompt and attempting to use negation will result in the opposite of what you intend. For example, a prompt such as "a fruit basket with no bananas" will actually signal the model to include bananas. Instead, you can use a negative prompt, via the negative prompt, to specify any objects or characteristics that you want to exclude from the image. For example "bananas".

## Output format
Please break down the following scene description into shots and output in a concise JSON format:
{
    "story":"expand the input and write as a story less than 50 words,use the same language as the user input",
    "shots": [
        {
            "id": "shot_1",
            "caption":"caption for this shot, limt to less than 2 sentences, use the same language as the user input",
            "lighting": "lighting details",
            "cinematography": "Specify camera motion (avoid complex camera movements),refer to 'Camera Prompt 运镜指南' in document. ",
            "prompt": "prompt in English, adding the keywords from lighting and cinematography",
            "negative_prompt": "(optional) negative English prompt"

        }
    ]
}

## Example
场景描述：一个女孩在黄昏时分走在海边的沙滩上，远处是落日和帆船。

输出：
{
    "story": "黄昏时分，一个孤独的女孩漫步在宁静的海岸线上。夕阳将天空渲染成充满活力的橙色和紫色，远处的帆船在地平线上静静地漂浮。她的脚印在金色的沙滩上留下一道痕迹，温柔的海浪轻抚着海岸，构成了一幅完美宁静的画面。",
    "shots": [
        {
            "id": "shot_1",
            "caption": "金色的夕阳洒满海滩，远处的帆船与橙红色的天空勾勒出完美的剪影。",
            "lighting": "Warm backlight from setting sun, golden hour",
            "cinematography": "dolly in",
            "prompt": "cinematic wide shot beach sunset, golden hour, sailboats on horizon, calm ocean, warm orange sky,  high resolution, dolly in, cinematic",
            "negative_prompt": "people, buildings, oversaturated"
        },
        {
            "id": "shot_2",
            "caption": "少女孤独的身影在夕阳下漫步，在金色沙滩上留下一串蜿蜒的脚印。",
            "lighting": "Strong backlight creating silhouette",
            "cinematography": "pan right",
            "prompt": "silhouette young girl walking beach sunset, golden sand, peaceful atmosphere, soft warm lighting, high resolution,pan right, cinematic",
            "negative_prompt": "groups, urban elements, harsh shadows"

        },
        {
            "id": "shot_3",
            "caption": "几艘帆船静静地漂浮在天海相接处，在绚丽的晚霞中形成优美的剪影。",
            "lighting": "Dramatic sunset backlighting",
            "cinematography": "zoom out",
            "prompt": "sailboats silhouetted sunset ocean horizon, orange sky, calm sea, golden hour lighting, zoom out, cinematic",
            "negative_prompt": "storms, rough seas, modern boats"

        }
    ]
}
"""

system_division_2 = """
You are a screenwriter, and I need your help to rewrite and expand the input to a story and then break down the following scene description into a series of storyboard shots. Each shot should:
- Include a clear focal point
- Describe specific visual elements (such as composition, lighting, angle, etc.)
- Be suitable for AI image generation
- Use concise English descriptions
- Add key artistic style and mood tags
- Contain 3 shots

## Notes
- Prompting for image generation models differs from prompting for large language models (LLMs). Image generation models do not have the ability to reason or interpret explicit commands. Therefore, it's best to phrase your prompt as if it were an image caption rather than a command or conversation.
- Consider adding modifiers like aspect ratios, image quality settings, or post-processing instructions to refine the output.
- Avoid topics such as pornography, racial discrimination, and toxic words.
- Do not use negation words like "no", "not", "without", and so on in your prompt. The model doesn't understand negation in a prompt and attempting to use negation will result in the opposite of what you intend. For example, a prompt such as "a fruit basket with no bananas" will actually signal the model to include bananas. Instead, you can use a negative prompt, via the negative prompt, to specify any objects or characteristics that you want to exclude from the image. For example "bananas".

## Output format
Please break down the following scene description into shots and output in a concise JSON format:
{
    "story":"expand the input and write as a story less than 100 words,use the same language as the user input",
    "shots": [
        {
            "id": "shot_1",
            "caption":"caption for this shot, limt to less than 2 sentences, use the same language as the user input",
            "description": "scene description, use the same language as user input",
            "composition": "composition details",
            "lighting": "lighting details",
            "angle": "angle details",
            "distance": "shot distance details",
            "style_tags": ["tag1", "tag2", "tag3"],
            "prompt": "English prompt",
            "negative_prompt": "(optional) negative English prompt"
        }
    ]
}

## Example
场景描述：一个女孩在黄昏时分走在海边的沙滩上，远处是落日和帆船。

输出：
{
    "story": "黄昏时分，一个孤独的女孩漫步在宁静的海岸线上。夕阳将天空渲染成充满活力的橙色和紫色，远处的帆船在地平线上静静地漂浮。她的脚印在金色的沙滩上留下一道痕迹，温柔的海浪轻抚着海岸，构成了一幅完美宁静的画面。",
    "shots": [
        {
            "id": "shot_1",
            "caption": "金色的夕阳洒满海滩，远处的帆船与橙红色的天空勾勒出完美的剪影。",
            "description": "A vast beach scene at golden hour, with sailboats silhouetted against an orange sky",
            "composition": "Rule of thirds, horizon line in upper third",
            "lighting": "Warm backlight from setting sun, golden hour",
            "angle": "Wide angle, straight on",
            "distance": "Extreme wide shot",
            "style_tags": ["cinematic", "atmospheric", "golden hour"],
            "prompt": "cinematic wide shot beach sunset, golden hour, sailboats on horizon, calm ocean, warm orange sky, 16:9 aspect ratio, high resolution, photorealistic",
            "negative_prompt": "people, buildings, oversaturated"
        },
        {
            "id": "shot_2",
            "caption": "少女孤独的身影在夕阳下漫步，在金色沙滩上留下一串蜿蜒的脚印。",
            "description": "Silhouette of a girl walking along beach with sunset backdrop",
            "composition": "Subject on left third, leading lines from footprints",
            "lighting": "Strong backlight creating silhouette",
            "angle": "Eye level",
            "distance": "Medium wide shot",
            "style_tags": ["silhouette", "peaceful", "romantic"],
            "prompt": "silhouette young girl walking beach sunset, golden sand, peaceful atmosphere, soft warm lighting, photorealistic style, 16:9 aspect ratio",
            "negative_prompt": "groups, urban elements, harsh shadows"
        },
        {
            "id": "shot_3",
            "caption": "几艘帆船静静地漂浮在天海相接处，在绚丽的晚霞中形成优美的剪影。",
            "description": "Several sailboats drifting on horizon against orange sky",
            "composition": "Boats arranged across frame, strong horizontal lines",
            "lighting": "Dramatic sunset backlighting",
            "angle": "Straight on",
            "distance": "Long shot",
            "style_tags": ["maritime", "sunset", "peaceful"],
            "prompt": "sailboats silhouetted sunset ocean horizon, orange sky, calm sea, golden hour lighting, cinematic composition, photorealistic",
            "negative_prompt": "storms, rough seas, modern boats"
        }
    ]
}
"""


system_division = """
我需要你帮我把以下场景描述拆分成一系列分镜。每个分镜都应该：
1. 包含一个清晰的画面重点
2. 描述具体的视觉元素(如构图、光线、视角等)
3. 适合用于AI图像生成
4. 使用简洁的英文描述
5. 添加关键的艺术风格和氛围标签
6. 镜头不超过3个

#注意事项
- Prompting for image generation models differs from prompting for large language models (LLMs). Image generation models do not have the ability to reason or interpret explicit commands. Therefore, it's best to phrase your prompt as if it were an image caption rather than a command or conversation.
- Consider adding modifiers like aspect ratios, image quality settings, or post-processing instructions to refine the output.
- Avoid topics such as pornography, racial discrimination, and toxic words.
- Do not use negation words like "no", "not", "without", and so on in your prompt. The model doesn't understand negation in a prompt and attempting to use negation will result in the opposite of what you intend. For example, a prompt such as "a fruit basket with no bananas" will actually signal the model to include bananas. Instead, you can use a negative prompt, via the negative prompt, to specify any objects or characteristics that you want to exclude from the image. For example "bananas".

请将以下场景描述拆分为分镜，并以精简的 JSON 格式输出：
{
    "shots": [
        {
            "id": "shot_1",
            "description": "场景描述",
            "composition": "构图说明",
            "lighting": "光线说明",
            "angle": "视角说明",
            "distance": "景别说明",
            "style_tags": ["标签1", "标签2", "标签3"],
            "prompt": "英文提示词",
            "negative_prompt": "(可选)负向提示词"
        }
    ]
}


##示例##
场景描述：一个女孩在黄昏时分走在海边的沙滩上，远处是落日和帆船。

输出：
{
    "shots": [
        {
            "id": "shot_1",
            "description": "远景镜头，展现黄昏海滩的整体氛围",
            "composition": "wide angle composition",
            "lighting": "natural sunset lighting",
            "angle": "eye level",
            "distance": "long shot",
            "style_tags": ["cinematic", "golden hour", "peaceful", "warm colors"],
            "prompt": "wide shot of a beach at sunset, golden hour, sailing boats on horizon, cinematic lighting",
            "negative_prompt":""
        },
        {
            "id": "shot_2",
            "description": "女孩的背影剪影",
            "composition": "rule of thirds",
            "lighting": "backlight",
            "angle": "side view",
            "distance": "medium shot",
            "style_tags": ["atmospheric", "moody", "dramatic", "silhouette"],
            "prompt": "silhouette of a girl walking on beach, sunset backdrop, side view, dramatic lighting",
            "negative_prompt":"wrong leg"
        },
        {
            "id": "shot_3",
            "description": "特写镜头展现女孩的表情和周围环境细节",
            "composition": "centered composition",
            "lighting": "side lighting",
            "angle": "eye level",
            "distance": "close-up",
            "style_tags": ["portrait", "emotional", "soft lighting", "intimate"],
            "prompt": "close-up shot of a girl's face, warm sunset light, beach background, soft focus",
            "negative_prompt":""
        }
    ]
}
"""

system_nova_reel_2 = \
"""
You are a Prompt rewriting expert for image-to-video models, with expertise in film industry knowledge and skilled at helping users output final text prompts based on input initial frame images and potentially accompanying text prompts. 
The main goal is to help other models produce better video outputs based on these prompts and initial frame images. Users may input only images or both an image and text prompt, where the text could be in Chinese or English.
Your final output should be a single paragraph of English prompt not exceeding 90 words.

##You are proficient in the knowledge mentioned in:##
-You have a comprehensive understanding of the world, knowing various physical laws and can envision video content showing interactions between all things.
-You are imaginative and can envision the most perfect, visually impactful video scenes based on user-input images and prompts.
-You possess extensive film industry knowledge as a master director, capable of supplementing the best cinematographic language and visual effects based on user-input images and simple descriptions.


##Please follow these guidelines for rewriting prompts:##
-Subject: Based on user-uploaded image content, describe the video subject's characteristics in detail, emphasizing details while adjusting according to user's text prompt.
-Scene: Detailed description of video background, including location, environment, setting, season, time, etc., emphasizing details.
-Emotion and Atmosphere: Description of emotions and overall atmosphere conveyed in the video, referencing the image and user's prompt.
-Cinematography: Specify shot types, camera angles, and perspectives, Please refer to the guideline in DocumentPDFmessages.
-Visual Effects: Description of the visual style from user-uploaded images, such as Pixar animation, film style, realistic style, 3D animation, including descriptions of color schemes, lighting types, and contrast.

##Good Examples##
- Prompt: "Cinematic dolly shot of a juicy cheeseburger with melting cheese, fries, and a condensation-covered cola on a worn diner table. Natural lighting, visible steam and droplets. 4k, photorealistic, shallow depth of field"
- Prompt: "Arc shot on a salad with dressing, olives and other vegetables; 4k; Cinematic;"
- Prompt: "First person view of a motorcycle riding through the forest road."
- Prompt: "Closeup of a large seashell in the sand. Gentle waves flow around the shell. Camera zoom in."
- Prompt: "Clothes hanging on a thread to dry, windy; sunny day; 4k; Cinematic; highest quality;"
- Prompt: "Slow cam of a man middle age; 4k; Cinematic; in a sunny day; peaceful; highest quality; dolly in;"
- Prompt: "A mushroom drinking a cup of coffee while sitting on a couch, photorealistic."

##Ouput instruction##
Users may input prompts in Chinese or English, but your final output should be a single English paragraph not exceeding 80 words.
Put your reponse in <prompt></prompt>

"""

config = Config(
       connect_timeout=1000,
    read_timeout=1000,
)

BUCKET = "s3://bedrock-video-generation-us-east-1-209483906212/video/output/"
RESULT_QR_BUCKET = "bedrock-video-generation-us-east-1-209483906212"
session = boto3.session.Session(region_name='us-east-1')
bedrock_runtime = session.client(service_name = 'bedrock-runtime', 
                                 config=config)

aws_region_s3 = "us-east-1"

def upload_to_s3(local_file, bucket, s3_file):
    s3 = boto3.client('s3', region_name=aws_region_s3)
    try:
        s3.upload_file(local_file, bucket, s3_file)
        logger.info(f"Upload Successful: {s3_file}")
        return True
    except FileNotFoundError:
        logger.info("The file was not found")
        return False
    except NoCredentialsError:
        logger.info("Credentials not available")
        return False

def generate_s3_url(bucket, s3_file):
    s3 = boto3.client('s3', region_name=aws_region_s3)
    file_extension = s3_file.lower().split('.')[-1]
    if file_extension == 'mp4':
        params = {'Bucket': bucket, 'Key': s3_file,'ResponseContentType': 'video/mp4','ResponseContentDisposition': f'attachment; filename="{s3_file}"'}
    elif file_extension == 'png':
        params = {'Bucket': bucket, 'Key': s3_file}
    url = s3.generate_presigned_url('get_object',
                                Params=params,
                                ExpiresIn=3600*24*7)  # URL有效期为7天
    return url



class ImageError(Exception):
    "Custom exception for errors returned by Amazon Nova Canvas"

    def __init__(self, message):
        self.message = message

#def split_caption(text):
#    delimiters = [',', '，', '。', '.', '!', '！', '?', '？', ';', '；', ' ', '\n', '\t']
#    pattern = '|'.join(map(re.escape, delimiters))
#    parts = re.split(pattern, text)
#    return parts

def split_caption(text):
    # delimiters = [',', '，', '。', '.', '!', '！', '?', '？', ';', '；', ' ', '\n', '\t']
    delimiters = [',', '，', '。', '.', ';', '；', '\n', '\t']
    pattern = '|'.join(map(re.escape, delimiters))
    parts = re.split(pattern, text)
    return parts

def add_timed_captions(video_path, output_path, captions,font='./yahei.ttf'):
    # Load the video
    video = VideoFileClip(video_path)
    
    # Create text clips for each caption
    txt_clips = []
    
    for caption in captions:
        text, start_time, end_time = caption
        txt_clip = TextClip(text=text, font_size=50, color='white', font=font,text_align='center',margin=(20,20))
        txt_clip = txt_clip.with_position('bottom').with_start(start_time).with_end(end_time)
        txt_clips.append(txt_clip)
    
    # Combine video and all text clips
    final_video = CompositeVideoClip([video] + txt_clips)
    
    # Write output video
    final_video.write_videofile(output_path)
    
    # Close clips
    video.close()
    final_video.close()

def stitch_videos(video1_path: str, video2_path: str, output_path: str):
    """
    Stitches two videos together and saves the result to a new file.

    Args:
        video1_path (str): The file path to the first video.
        video2_path (str): The file path to the second video.
        output_path (str): The file path to save the stitched video.
    """
    # Load the video clips
    clip1 = VideoFileClip(video1_path)
    clip2 = VideoFileClip(video2_path)

    final_clip = [
        clip1,
        clip2.with_start(clip1.duration),
    ]

    # Concatenate the clips
    final_clip = CompositeVideoClip(final_clip)

    # Write the result
    final_clip.write_videofile(output_path)

    # Clean up
    clip1.close()
    clip2.close()
    final_clip.close()
    logger.info(f"Stitched video saved to {output_path}")
    return output_path

def download_video_from_s3(s3_uri, local_path):
    """
    Download a video file from S3 to local storage
    
    Parameters:
    s3_uri (str): S3 URI in format 's3://bucket-name/path/to/video.mp4'
    local_path (str): Local path where the video will be saved
    """
    try:
        # Initialize S3 client
        s3_client = boto3.client('s3')
        
        # Parse S3 URI to get bucket and key
        if not s3_uri.startswith('s3://'):
            raise ValueError("Invalid S3 URI format. Must start with 's3://'")
        
        # Remove 's3://' and split into bucket and key
        path_parts = s3_uri[5:].split('/', 1)
        if len(path_parts) != 2:
            raise ValueError("Invalid S3 URI format")
        
        bucket_name = path_parts[0]
        s3_key = path_parts[1]
        
        # Create directory if it doesn't exist
        os.makedirs(local_path, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        fname = timestamp+random_string_name()+'.mp4'
        # Download the file
        logger.info(f"Downloading {s3_uri} to {local_path}/{fname}")
        s3_client.download_file(bucket_name, s3_key, local_path+'/'+fname)
        logger.info("Download completed successfully!")
        
        return f"{local_path}/{fname}"
        
    except Exception as e:
        logger.info(f"Error downloading file: {str(e)}")
        return False

def random_string_name(length=12):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


def img_mime(image_path):
    try:
        mime = magic.Magic(mime=True)
        return mime.from_file(image_path)
    
    except Exception as e:
        logger.info(f"python-magic detection error: {str(e)}")
        return None

def parse(text: str) -> str:
    pattern = r"<prompt>(.*?)</prompt>"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        text = match.group(1)
        return text.strip()
    else:
        raise JSONDecodeError

def invoke_nova(system, messages):

    # Configure the inference parameters.
    inf_params = {"maxTokens": 2000, "topP": 0.9, "temperature": 0.8}

    # model_response = bedrock_runtime.converse_stream(
    #     modelId=PRO_MODEL_ID, messages=messages, system=system, inferenceConfig=inf_params
    # )

    # text = ""
    # stream = model_response.get("stream")
    # if stream:
    #     for event in stream:
    #         if "contentBlockDelta" in event:
    #             text += event["contentBlockDelta"]["delta"]["text"]
    #             #logger.info(event["contentBlockDelta"]["delta"]["text"])
    # print("system prompt",system,"text",text)
    model_response = bedrock_runtime.converse(
        modelId=PRO_MODEL_ID, messages=messages, system=system, inferenceConfig=inf_params
    )

    text = model_response["output"]["message"]["content"][0]["text"]

    print("system prompt",system,"text",text)
    return json.loads(text[:-3])


def generate_imageBgReplace(prompt,reference_image_path,production,save_filepath):
    # Load all reference images as base64.
    image_base64 = None
    with open(reference_image_path, "rb") as reference_image:
        image_base64=base64.b64encode(reference_image.read()).decode("utf-8")

    mask_prompt = production
    print("bgReplace prompt",prompt)
    # Configure the inference parameters.
    inference_params = {
        "taskType": "OUTPAINTING",
        "outPaintingParams": {
            "image": image_base64,
            "text": prompt,
            "maskPrompt": mask_prompt,
            "outPaintingMode": "PRECISE",
        },
        "imageGenerationConfig": {
            "numberOfImages": 1,
            "quality": "premium",
            "cfgScale": 6.5,
            "seed": random.randint(10000, 99999)
        }
    }        
    body = json.dumps(inference_params)
    try:
        image_bytes_ret = generate_image( body=body)
        for idx,image_bytes in enumerate(image_bytes_ret):
            image = Image.open(io.BytesIO(image_bytes))
            image.save(save_filepath)
            logger.info(f"image saved to {save_filepath}")
            # image.show()
    except Exception as err:
        logger.info(str(err))

def generate_text2img(prompt,negative_prompt,save_filepath):
    textToImageParams =  { "text": prompt}
    if len(negative_prompt):
        textToImageParams["negativeText"] = negative_prompt 
    body = json.dumps({
        "taskType": "TEXT_IMAGE",
        "textToImageParams": textToImageParams,
        "imageGenerationConfig": {
            "numberOfImages": 1,
            "height": 720,
            "width": 1280,
            "cfgScale": 6.5,
            "seed": random.randint(100, 99999)
        }
    })
    try:
        image_bytes_ret = generate_image( body=body)
        logger.info(f"num:{len(image_bytes_ret)}")
        # logger.info(f"image_bytes:{image_bytes_ret[:20]}")

        for idx,image_bytes in enumerate(image_bytes_ret):
            image = Image.open(io.BytesIO(image_bytes))
            image.save(save_filepath)  
            logger.info(f"image saved to {save_filepath}")
            # image.show()
        return save_filepath

    except Exception as err:
        logger.info(str(err))

def generate_variations(reference_image_paths,prompt,negative_prompt,save_filepath):
    # Load all reference images as base64.
    images = []
    for path in reference_image_paths:
        with open(path, "rb") as image_file:
            images.append(base64.b64encode(image_file.read()).decode("utf-8"))

    # Configure the inference parameters.
    inference_params = {
        "taskType": "IMAGE_VARIATION",
        "imageVariationParams": {
            "images": images, # Images to use as reference
            "text": prompt, 
            "similarityStrength": 0.9,  # Range: 0.2 to 1.0
        },
        "imageGenerationConfig": {
            "numberOfImages": 1,  # Number of variations to generate. 1 to 5.
            "quality": "standard",  # Allowed values are "standard" and "premium"
            "width": 1280,  # See README for supported output resolutions
            "height": 720,  # See README for supported output resolutions
            "cfgScale": 4.0,  # How closely the prompt will be followed
            "seed": random.randint(100, 99999)
        },
    }
    if len(negative_prompt):
        inference_params['imageVariationParams']["negativeText"] = negative_prompt
        
    body = json.dumps(inference_params)
    try:
        image_bytes_ret = generate_image( body=body)
        for idx,image_bytes in enumerate(image_bytes_ret):
            image = Image.open(io.BytesIO(image_bytes))
            image.save(save_filepath)
            logger.info(f"image saved to {save_filepath}")
            # image.show()
    except Exception as err:
        logger.info(str(err))


def generate_image(body):
    """
    Generate an image using Amazon Nova Canvas model on demand.
    Args:
        body (str) : The request body to use.
    Returns:
        image_bytes (bytes): The image generated by the model.
    """
    accept = "application/json"
    content_type = "application/json"

    response = bedrock_runtime.invoke_model(
        body=body, modelId='amazon.nova-canvas-v1:0', accept=accept, contentType=content_type
    )
    response_body = json.loads(response.get("body").read())
    image_bytes_list = []
    if "images" in response_body:
        logger.info(f"num of images:{len(response_body['images'])}")
        for base64_image in response_body["images"]:
            base64_bytes = base64_image.encode('ascii')
            image_bytes = base64.b64decode(base64_bytes)
            image_bytes_list.append(image_bytes)

    finish_reason = response_body.get("error")

    if finish_reason is not None:
        raise ImageError(f"Image generation error. Error is {finish_reason}")

    return image_bytes_list


def optimize_reel_prompt(system,user_prompt,ref_image,doc_bytes):
    with open(ref_image, "rb") as f:
        image = f.read()
    mime_type = img_mime(ref_image)

    system = [
        {
            "text": system
        }
    ]
    messages = [
        {
            "role": "user",
            "content": [
             {
                "document": {
                    "format": "pdf",
                    "name": "DocumentPDFmessages",
                    "source": {
                        "bytes": doc_bytes
                    }
                }
            },
            {"image": {"format": mime_type.split('/')[1], "source": {"bytes": image}}},
             {"text": user_prompt},
            ],
        },
        {"role":"assistant",
         "content":
         [{"text": "I will reply within 80 words:"}]
        }
    ]

    # Configure the inference parameters.
    inf_params = {"maxTokens": 400, "topP": 0.9, "temperature": 0.5}


    model_response = bedrock_runtime.converse(
        modelId=PRO_MODEL_ID, messages=messages, system=system, inferenceConfig=inf_params
    )
    text = model_response["output"]["message"]["content"][0]["text"]

    # text = ""
    # stream = model_response.get("stream")
    # if stream:
    #     for event in stream:
    #         if "contentBlockDelta" in event:
    #             text += event["contentBlockDelta"]["delta"]["text"]
    #             #logger.info(event["contentBlockDelta"]["delta"]["text"])
    return parse(text)


def optimize_reel_prompt_no_img(system,user_prompt,doc_bytes):
    system = [
        {
            "text": system
        }
    ]
    messages = [
        {
            "role": "user",
            "content": [
             {
                "document": {
                    "format": "pdf",
                    "name": "DocumentPDFmessages",
                    "source": {
                        "bytes": doc_bytes
                    }
                }
            },
             {"text": user_prompt},
            ],
        },
        {"role":"assistant",
         "content":
         [{"text": 'I will reply within 80 words:'}]
        }
    ]

    # Configure the inference parameters.
    inf_params = {"maxTokens": 400, "topP": 0.9, "temperature": 0.5}

    model_response = bedrock_runtime.converse(
        modelId=PRO_MODEL_ID, messages=messages, system=system, inferenceConfig=inf_params
    )
    text = model_response["output"]["message"]["content"][0]["text"]

    # model_response = bedrock_runtime.converse_stream(
    #     modelId=PRO_MODEL_ID, messages=messages, system=system, inferenceConfig=inf_params
    # )
    # text = ""
    # stream = model_response.get("stream")
    # if stream:
    #     for event in stream:
    #         if "contentBlockDelta" in event:
    #             text += event["contentBlockDelta"]["delta"]["text"]
    return parse(text)

def generate_video(bucket,text_prompt,ref_image = None):
    model_input = {
        "taskType": "TEXT_VIDEO",
        "textToVideoParams": {
            "text": text_prompt,
        },
        "videoGenerationConfig": {
            "durationSeconds": 6,
            "fps": 24,
            "dimension": "1280x720",
            "seed": 0,  # Change the seed to get a different result
        },
    }

    if ref_image:
        with open(ref_image, "rb") as f:
            image = f.read()
            input_image_base64 = base64.b64encode(image).decode("utf-8")
            model_input['textToVideoParams']['images'] = [
            {
                "format": img_mime(ref_image).split('/')[1],
                "source": {
                    "bytes": input_image_base64
                }
            }
            ]
    try:
        # Start the asynchronous video generation job.
        invocation = bedrock_runtime.start_async_invoke(
            modelId="amazon.nova-reel-v1:0",
            modelInput=model_input,
            outputDataConfig={
                "s3OutputDataConfig": {
                    "s3Uri": BUCKET
                }
            }
        )
        return invocation

    except Exception as e:
        # Implement error handling here.
        message = e.response["Error"]["Message"]
        logger.info(f"Error: {message}")
        return None

def generate_video_by_base64(bucket,text_prompt,ref_image_base64 = None):
    model_input = {
        "taskType": "TEXT_VIDEO",
        "textToVideoParams": {
            "text": text_prompt,
        },
        "videoGenerationConfig": {
            "durationSeconds": 6,
            "fps": 24,
            "dimension": "1280x720",
            "seed": 0,  # Change the seed to get a different result
        },
    }

    if ref_image_base64:
        model_input['textToVideoParams']['images'] = [
        {
            "format": "png",
            "source": {
                "bytes": ref_image_base64
            }
        }
        ]
    try:
        # Start the asynchronous video generation job.
        invocation = bedrock_runtime.start_async_invoke(
            modelId="amazon.nova-reel-v1:0",
            modelInput=model_input,
            outputDataConfig={
                "s3OutputDataConfig": {
                    "s3Uri": BUCKET
                }
            }
        )
        return invocation

    except Exception as e:
        # Implement error handling here.
        message = e.response["Error"]["Message"]
        logger.info(f"Error: {message}")
        return None


    
import cv2
import base64
import numpy as np
import ffmpeg
import tempfile
import os


def get_last_frame_base64_v2(video_path):
    try:
        # 使用FFmpeg获取视频信息
        probe = ffmpeg.probe(video_path)
        video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        duration = float(video_info['duration'])
        
        # 计算最后2秒的起始时间
        start_time = max(0, duration - 2)
        
        # 创建临时目录来存储I帧
        with tempfile.TemporaryDirectory() as temp_dir:
            # 使用FFmpeg提取最后2秒的I帧
            (
                ffmpeg
                .input(video_path, ss=start_time)
                .filter('select', 'eq(pict_type,I)')
                .output(f'{temp_dir}/frame%03d.png', vframes=48)
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            # 读取所有提取的I帧
            frames = []
            for filename in sorted(os.listdir(temp_dir)):
                if filename.endswith('.png'):
                    frame = cv2.imread(os.path.join(temp_dir, filename))
                    if frame is not None:
                        frames.append(frame)        
        if not frames:
            logger.info("Error: Could not extract any I-frames")
            return None
        
        # 选择最清晰的帧（这里使用简单的方差作为清晰度度量）
        best_frame = max(frames, key=lambda f: np.var(cv2.Laplacian(f, cv2.CV_64F)))
        
        # 应用简单的锐化
        #kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        #sharpened = cv2.filter2D(best_frame, -1, kernel)
        
        # 使用PNG格式进行无损编码，设置最高质量
        _, buffer = cv2.imencode('.png', best_frame, [cv2.IMWRITE_PNG_COMPRESSION, 0])
        
        # 将图像转换为base64编码
        base64_image = base64.b64encode(buffer).decode('utf-8')
        
        return base64_image
    except Exception as e:
        logger.info(f"Error: {str(e)}")
        return None

def get_last_frame_base64(video_path):
    return get_last_frame_base64_v3(video_path)


def get_last_frame_base64_v3(video_path):
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.info("Error: Could not open video file")
            return None
        
        # 获取视频信息
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # 计算最后2秒对应的帧数
        frames_in_1_seconds = int(fps * 1)
        start_frame = max(0, total_frames - frames_in_1_seconds)
        
        frames = []
        # 设置读取位置到最后2秒开始处
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        
        # 读取最后2秒的所有帧
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frames.append(frame)
        
        cap.release()
        
        if not frames:
            logger.info("Error: Could not read any valid frames")
            return None
        
        # 选择最清晰的帧
        best_frame = max(frames, key=lambda f: np.var(cv2.Laplacian(f, cv2.CV_64F)))
        
        # 使用PNG格式进行无损编码
        _, buffer = cv2.imencode('.png', best_frame, [cv2.IMWRITE_PNG_COMPRESSION, 0])
        
        # 转换为base64编码
        base64_image = base64.b64encode(buffer).decode('utf-8')
        
        return base64_image
    except Exception as e:
        logger.info(f"Error: {str(e)}")
        return None
    
def get_last_frame_base64_v1(video_path):
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.info("Error: Could not open video file")
            return None
        # 获取视频信息
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps
        frames = []
        # 首先尝试使用时间戳定位
        start_time = max(0, duration - 1)  # 1000毫秒 = 1秒
        print("start_time:",start_time)
        success = cap.set(cv2.CAP_PROP_POS_MSEC, start_time*1000)
        
        # 如果时间戳定位失败，使用帧数定位
        if not success:
            logger.info("Time-based positioning failed, switching to frame-based positioning")
            frames_in_1_seconds = int(fps * 1)
            start_frame = max(0, total_frames - frames_in_1_seconds)
            success = cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            
            if not success:
                logger.info("Both positioning methods failed")
                cap.release()
                return None
        
        # 读取最后1秒的所有帧
        frame_count = 0
        max_frames = int(fps * 1)  # 最多读取1秒的帧数
        
        while frame_count < max_frames:
            ret, frame = cap.read()
            if not ret:
                break
            frames.append(frame)
            frame_count += 1
        
        cap.release()
        
        if not frames:
            logger.info("Error: Could not read any valid frames")
            return None
        
        # 选择最清晰的帧
        # 使用Laplacian算子计算每帧的清晰度
        best_frame = max(frames, key=lambda f: cv2.Laplacian(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
        
        # 使用PNG格式进行无损编码
        try:
            _, buffer = cv2.imencode('.png', best_frame, [cv2.IMWRITE_PNG_COMPRESSION, 0])
        except Exception as e:
            logger.info(f"Error during image encoding: {str(e)}")
            return None
        
        # 转换为base64编码
        try:
            base64_image = base64.b64encode(buffer).decode('utf-8')
            return base64_image
        except Exception as e:
            logger.info(f"Error during base64 encoding: {str(e)}")
            return None
            
    except Exception as e:
        logger.info(f"Error: {str(e)}")
        return None
    finally:
        if 'cap' in locals() and cap is not None:
            cap.release()
    
def generate_video_sequnce(reel_prompts,image_files):
    video_files = []
    ###连续视频只有第一张图片
    image_file=image_files[0]
    try:
        for prompt in reel_prompts:
            if len(video_files)==0:
                ### 第一个视频，使用生成的image
                invocation = generate_video(bucket= BUCKET, text_prompt = prompt,ref_image=image_file)
                responses = fetch_job_status([invocation['invocationArn']])
                output_uri = responses[0]['outputDataConfig']['s3OutputDataConfig']['s3Uri']+'/output.mp4'
                file_name = download_video_from_s3(output_uri,'./generated_videos')      
                video_files.append(file_name)
            else:
                ### 取上一个生成的video_files中的视频的最后一帧，作为该次生成时候的ref_image
                ref_image_base64=get_last_frame_base64(video_files[-1])
                invocation = generate_video_by_base64(bucket= BUCKET, text_prompt = prompt,ref_image_base64=ref_image_base64)
                responses = fetch_job_status([invocation['invocationArn']])
                output_uri = responses[0]['outputDataConfig']['s3OutputDataConfig']['s3Uri']+'/output.mp4'
                file_name = download_video_from_s3(output_uri,'./generated_videos')      
                video_files.append(file_name)
        return video_files
    except Exception as e:
        logger.info(f"Error: {str(e)}")
        return None
    
        
    

def generate_video_batch(prompts,image_files):
    invocation_arns = []
    for prompt,image_file in zip(prompts,image_files):
        invocation = generate_video(bucket= BUCKET, text_prompt = prompt,ref_image=image_file)
        invocation_arns.append(invocation['invocationArn'])
    return invocation_arns

def fetch_job_status(invocation_arns):
    final_responses = []
    for invocation in invocation_arns:
        while 1:
            response = bedrock_runtime.get_async_invoke(
                invocationArn=invocation
            )
            status = response["status"]
            logger.info(f"{invocation}: {status}")
            time.sleep(5)
            if not status == 'InProgress':
                final_responses.append(response)
                break
    return final_responses

def get_production_main(user_prompt):
    system = [
        {
            "text": """Extract the product subject from the following text description and return the product subject name in JSON format: 
            { 
              "result":"production name"
            }
            do not including any other information in response"""
        }
    ]
    messages = [
        {
            "role": "user",
            "content": [
             {"text": user_prompt},
            ],
        },
        {
             "role": "assistant",
             "content": [
             {"text": "```json"},
            ]
        }
    ]
    production = invoke_nova(system=system,messages=messages)
    return production['result']

def get_divison_shots(system_prompt,user_prompt):
    system = [
        {
            "text": system_prompt
        }
    ]
    messages = [
        {
            "role": "user",
            "content": [
             {"text": user_prompt},
            ],
        },
        {
             "role": "assistant",
             "content": [
             {"text": "```json"},
            ]
        }
    ]
    shots = invoke_nova(system=system,messages=messages)
    return shots