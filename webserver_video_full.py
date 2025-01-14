import gradio as gr
import json
from urllib import request
import time
import os
import subprocess
from anthropic import AnthropicBedrock
import base64
import io
import json
import logging
import boto3
from PIL import Image
from botocore.config import Config
from botocore.exceptions import ClientError
import uuid
import math
import random
from util import *

#################### 0. Basic Configuration ####################
aws_region_claude = "us-west-2"
aws_region_nova = "us-east-1"

session = boto3.session.Session(region_name='us-east-1')
bedrock_runtime = session.client(service_name = 'bedrock-runtime', 
                                 config=config)

PRO_MODEL_ID = "us.amazon.nova-pro-v1:0"
LITE_MODEL_ID = "us.amazon.nova-lite-v1:0"
MICRO_MODEL_ID = "us.amazon.nova-micro-v1:0"

claude_model_id = "anthropic.claude-3-5-sonnet-20241022-v2:0"
nova_model_id = 'amazon.nova-canvas-v1:0'
nova_height = 720
nova_width = 1280
nova_quality = "premium"
nova_cfg_scale = 6
nova_seed = 2352356

flux_wait_time = 15
flux_store_dir = "/opt/program/ComfyUI/output"

server_address = "comfy.yugaozh-flow.com"
shots = []

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

#################### 1. Prompt Enhance ####################
# 使用Bedrock/Claude3进行提示词增强，包括两个步骤：
# 1. 将中文提示词进行扩展，加入更多元素
# 2. 将扩展后的提示词进行文生图专业提示词生成（包括转换成英文）

user_prompt_template = """
    <question>
    {QUESTION}
    </question>
"""

claude_client = AnthropicBedrock(
    # Authenticate by either providing the keys below or use the default AWS credential providers, such as
    # using ~/.aws/credentials or the "AWS_SECRET_ACCESS_KEY" and "AWS_ACCESS_KEY_ID" environment variables.
    # aws_access_key="<access key>",
    # aws_secret_key="<secret key>",
    # Temporary credentials can be used with aws_session_token.
    # aws_session_token="<session_token>",
    aws_region=aws_region_claude,
)

def _claude_send_message(client, model_id, max_tokens, system_prompt, user_message):
    response = client.messages.create(
        model=model_id,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[user_message]
    )

    return response.content[0].text


# 1. 提示词扩展
system_prompt_template_extension = """You are a prompt generator specialized in text to image.
    Expand the statement within the <question> tag into 4-5 sentences, retaining the original message while incorporating visual elements like clouds, oceans, and landscapes. 
    Maintain the core theme but enrich it with natural imagery.
    Only generate extended prompt themselves, do not generate other information.
    Output language should be same with input <question> tag language. For examples, if language of input is Chinese, output is still be Chinese.
    """
max_tokens_extension = 1024

def _prompt_extension(user_prompt):
    user_message = {"role": "user", "content": user_prompt}
    prompt_extension = _claude_send_message(client=claude_client,
                                            model_id=claude_model_id,
                                            max_tokens=max_tokens_extension,
                                            system_prompt=system_prompt_template_extension,
                                            user_message=user_message)
    return prompt_extension

# 2. 提示词增强
system_prompt_template_enhance = """You are a prompt generator specialized in text to image. Generated prompt should be in English and high quality.
    Translate the question within the <question> tag in the end into text to image prompt.
    Only generate prompt themselves, do not generate other information, such as postive/negative prompt.
    """
max_tokens_enhance = 1024

def _prompt_enhance(user_prompt):
    user_message = {"role": "user", "content": user_prompt}
    prompt_enhance = _claude_send_message(client=claude_client,
                                          model_id=claude_model_id,
                                          max_tokens=max_tokens_enhance,
                                          system_prompt=system_prompt_template_enhance,
                                          user_message=user_message)
    return prompt_enhance



#################### 3. Nova Canvas    ####################
def _generate_image_nova(model_id, body):
    """
    Generate an image using Amazon Nova Canvas model on demand.
    Args:
        model_id (str): The model ID to use.
        body (str) : The request body to use.
    Returns:
        image_bytes (bytes): The image generated by the model.
    """

    logger.info("Generating image with Amazon Nova Canvas model")

    bedrock = boto3.client(
        service_name='bedrock-runtime',
        region_name=aws_region_nova,
        config=Config(read_timeout=300)
    )

    accept = "application/json"
    content_type = "application/json"

    response = bedrock.invoke_model(
        body=body, modelId=model_id, accept=accept, contentType=content_type
    )
    response_body = json.loads(response.get("body").read())

    base64_image = response_body.get("images")[0]
    base64_bytes = base64_image.encode('ascii')
    image_bytes = base64.b64decode(base64_bytes)

    finish_reason = response_body.get("error")

    if finish_reason is not None:
        raise ImageError(f"Image generation error. Error is {finish_reason}")

    logger.info(
        "Successfully generated image with Amazon Nova Canvas  model %s", model_id)

    return image_bytes


def generate_image_nova(user_prompt,video_type_radio):
    global system_division_2
    global system_sequnce
    print("单镜图像生成")
    shots = get_divison_shots(system_division_2,user_prompt)
    prompts = [ f"{p['prompt']} {p['composition']} angle:{p['angle']} {p['distance']} {p['lighting']} {' '.join(p['style_tags'])}" for p in shots['shots']]
    neg_prompts = [p['negative_prompt'] for p in shots['shots']]
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    output_dir=os.path.join('shot_images',timestamp)
    os.makedirs(output_dir, exist_ok=True)
    # 保存shots到json文件
    shots_json_path = os.path.join(output_dir, f'{timestamp}_shots.json')
    with open(shots_json_path, 'w', encoding='utf-8') as f:
        json.dump(shots, f, ensure_ascii=False, indent=2)

    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s: %(message)s")
    

    user_prompt = _prompt_enhance(user_prompt)
    logger.info(f"Enhanced  user prompt : {user_prompt}")
    
    image_files = []
    body = json.dumps({
        "taskType": "TEXT_IMAGE",
        "textToImageParams": {
            "text": user_prompt
        },
        "imageGenerationConfig": {
            "numberOfImages": 1,
            "height": nova_height,
            "width": nova_width,
            "quality": nova_quality,
            "cfgScale": nova_cfg_scale,
            "seed": random.randint(0, 2**10 - 1) 
        }
    })

    try:
        image_bytes = _generate_image_nova(model_id=nova_model_id,
                                           body=body)
        image = Image.open(io.BytesIO(image_bytes))
        save_path = os.path.join(output_dir,f'{timestamp}_shot_0.png')
        # 生成随机UUID
        image.save(save_path)  
        image_files.append(save_path)

        return image_files
        

    except ClientError as err:
        message = err.response["Error"]["Message"]
        logger.error("A client error occurred:", message)
        print("A client error occured: " +
              format(message))
    except ImageError as err:
        logger.error(err.message)
        print(err.message)


##################### 分镜头 image #############################
def create_divison_images(user_prompt,video_type_radio):
    logger.info("分镜图像生成")
    global system_division_2
    shots = get_divison_shots(system_division_2,user_prompt)
    prompts = [ f"{p['prompt']} {p['composition']} angle:{p['angle']} {p['distance']} {p['lighting']} {' '.join(p['style_tags'])}" for p in shots['shots']]
    neg_prompts = [p['negative_prompt'] for p in shots['shots']]
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    output_dir=os.path.join('shot_images',timestamp)
    os.makedirs(output_dir, exist_ok=True)
    # 保存shots到json文件
    shots_json_path = os.path.join(output_dir, f'{timestamp}_shots.json')
    with open(shots_json_path, 'w', encoding='utf-8') as f:
        json.dump(shots, f, ensure_ascii=False, indent=2)
    image_files = []
    for idx, prompt, neg_prompt in zip(range(len(prompts)),prompts,neg_prompts):
        logger.info(f"prompt:{prompt}\nneg_prompt:{neg_prompt}")
        save_path = os.path.join(output_dir,f'{timestamp}_shot_{idx}.png')
        #第一张图
        if not image_files: 
            generate_text2img(prompt,neg_prompt,save_path)
        else:
            generate_variations(image_files,prompt,neg_prompt,save_path)
        image_files.append(save_path)
        time.sleep(3)
    if video_type_radio == "连续视频":
        return [image_files[0]]
    else:
        return image_files

#####################. nova reel 生视频#########################

### option1: 分镜视频生成
def create_division_video(gradio_image_files,video_task_id=None):
    logger.info("分镜视频生成")
    global system_nova_reel_2
    nova_reel_system_prompt = system_nova_reel_2
    image_files=[]
    for item in gradio_image_files:
        image_files.append(item[0])
    
    # 查找对应的shots json
    ## 提取时间戳
    timestamp = None
    image_file_tmp=image_files[0]
    match = re.search(r'(\d+)_shot_\d+\.png', os.path.basename(image_file_tmp))
    if match:
        timestamp = match.group(1)
    if not timestamp:
        logger.info("No valid timestamp found in image files")
        return []
    
    # 构建shots json文件的路径
    directory="."
    shots_json_dir = os.path.join(directory, f"./shot_images/{timestamp}")
    shots_json_path = os.path.join(shots_json_dir, f"{timestamp}_shots.json")
    if not os.path.exists(shots_json_path):
        logger.info(f"No shots json file found at {shots_json_path}")
        return []

    try:
        with open(shots_json_path, 'r', encoding='utf-8') as f:
            shots = json.load(f)
    except Exception as e:
        logger.error(f"Error loading shots json file: {e}")
        return []
    
    with open("Amazon_Nova_Reel.pdf", "rb") as file:
        doc_bytes = file.read()
    reel_prompts = []
    for p,ref_img in zip(shots['shots'],image_files):
        logger.info(p['description'] )
        text = optimize_reel_prompt(nova_reel_system_prompt,p['description'],ref_img,doc_bytes)
        reel_prompts.append(text)
    
    invocation_arns = generate_video_batch(reel_prompts,image_files)
    final_responses = fetch_job_status(invocation_arns)
    video_files = []
    for response in final_responses:
        output_uri = response['outputDataConfig']['s3OutputDataConfig']['s3Uri']+'/output.mp4'
        file_name = download_video_from_s3(output_uri,'./generated_videos')
        video_files.append(file_name)
    
    ###分镜视频合成
    generated_fname = None
    for idx in range(len(video_files)-1):
        output_path = video_files[0].rsplit("/",1)[0]
        
        if video_task_id and str(video_task_id).strip():
            output_file_name = video_task_id
        else:
            output_file_name = random_string_name()
        
        if not generated_fname:
            generated_fname = stitch_videos(video_files[idx],video_files[idx+1],os.path.join(output_path,output_file_name+'.mp4'))
        else:
            generated_fname = stitch_videos(generated_fname,video_files[idx+1],os.path.join(output_path,output_file_name+'.mp4'))
    logger.info(f"Final stitch video:{generated_fname}")
    
    ###加字幕
    duration = 6
    captions = []
    for idx, p in enumerate(shots['shots']):
        desc_arr = split_caption(p['caption'])
        sub_duration = math.ceil(duration/len(desc_arr))
        for idy,sub_desc in enumerate(desc_arr):
            captions.append((desc_arr[idy],idx*duration+idy*sub_duration,idx*duration+(idy+1)*sub_duration))
    
    caption_video_file = os.path.splitext(generated_fname)[0]+"_caption.mp4"
    add_timed_captions(generated_fname,caption_video_file,captions)
    return caption_video_file

##option2 连续视频生成
def create_sequence_video(gradio_image_files,video_task_id=None):
    logger.info("连续视频生成")
    global system_nova_reel_2
    nova_reel_system_prompt = system_nova_reel_2
    
    image_files=[]
    for item in gradio_image_files:
        image_files.append(item[0])
    
    # 查找对应的shots json
    ## 提取时间戳
    timestamp = None
    image_file_tmp=image_files[0]
    match = re.search(r'(\d+)_shot_\d+\.png', os.path.basename(image_file_tmp))
    if match:
        timestamp = match.group(1)
    if not timestamp:
        logger.info("No valid timestamp found in image files")
        return []
    
    # 构建shots json文件的路径
    directory="."
    shots_json_dir = os.path.join(directory, f"./shot_images/{timestamp}")
    shots_json_path = os.path.join(shots_json_dir, f"{timestamp}_shots.json")
    if not os.path.exists(shots_json_path):
        logger.info(f"No shots json file found at {shots_json_path}")
        return []

    try:
        with open(shots_json_path, 'r', encoding='utf-8') as f:
            shots = json.load(f)
    except Exception as e:
        logger.error(f"Error loading shots json file: {e}")
        return []
    
    with open("Amazon_Nova_Reel.pdf", "rb") as file:
        doc_bytes = file.read()
    reel_prompts = []
    sequence_number = 0 
    
    for shot in shots['shots']:
        logger.info(shot['description'])
        #### 连续视频只有第一张图片
        if sequence_number == 0:
            ref_img = image_files[sequence_number]
            text = optimize_reel_prompt(nova_reel_system_prompt,shot['description'],ref_img,doc_bytes)
        else:
            text = optimize_reel_prompt_no_img(nova_reel_system_prompt,shot['description'],doc_bytes)
        sequence_number += 1
        reel_prompts.append(text)
    
    video_files = generate_video_sequnce(reel_prompts,image_files)
    ###连续视频合成
    generated_fname = None
    for idx in range(len(video_files)-1):
        output_path = video_files[0].rsplit("/",1)[0]
        if video_task_id and str(video_task_id).strip():
            output_file_name = video_task_id
        else:
            output_file_name = random_string_name()

        if not generated_fname:
            generated_fname = stitch_videos(video_files[idx],video_files[idx+1],os.path.join(output_path,output_file_name+'.mp4'))
        else:
            generated_fname = stitch_videos(generated_fname,video_files[idx+1],os.path.join(output_path,output_file_name+'.mp4'))
    logger.info(f"Final stitch video:{generated_fname}")
    
    ###加字幕
    duration = 6
    captions = []
    for idx, p in enumerate(shots['shots']):
        desc_arr = split_caption(p['caption'])
        sub_duration = math.ceil(duration/len(desc_arr))
        for idy,sub_desc in enumerate(desc_arr):
            captions.append((desc_arr[idy],idx*duration+idy*sub_duration,idx*duration+(idy+1)*sub_duration))
    
    caption_video_file = os.path.splitext(generated_fname)[0]+"_caption.mp4"
    add_timed_captions(generated_fname,caption_video_file,captions)
    return caption_video_file

#################### 6. Gradio         ####################

# 预置的提示词模版
PROMPT_TEMPLATES = {
    "风景模版": "一幅美丽的自然风景画，包含山脉和湖泊",
    "建筑模版": "一座宏伟的古代城堡，背景是夕阳",
    "亚马逊简单版": "我心目中的AWS像一个朋友，帮我在数字化转型的道路上披荆斩棘。",
    "亚马逊复杂版": "在一片广袤的科技星空下，AWS如一柄闪耀着银色光芒的利剑静静悬浮。这把利剑的剑身流转着云计算的灵动数据流，剑锋锐利如同切割黎明的第一缕阳光。当我握住剑柄的那一刻，数字化转型的荆棘丛生之路顿时豁然开朗，如同劈开浓雾见晴天。利剑所指之处，道路两旁绽放出创新的繁花，照亮了企业腾飞的征程，恰似黎明前升起的启明星指引着前行的方向。",
}

# 默认不进行提示词增强
prompt_enhanced_enabled = False
video_type = "sequnce"

def update_prompt(template_name):
    """
    更新 prompt 输入框的内容
    """
    return PROMPT_TEMPLATES.get(template_name, "")


def enhance_prompt(enhance_prompt_radio):
    
    global prompt_enhanced_enabled
    
    logger.info(f"Prompt enhanced radio : {enhance_prompt_radio}")

    if enhance_prompt_radio == "是":
        logger.info("Prompt enhanced enable.")
        prompt_enhanced_enabled = True        
    else:
        logger.info("Prompt enhanced disable.")
        prompt_enhanced_enabled = False

def video_type(video_type_radio):
    
    global video_type
    logger.info(f"Video type radio : {video_type_radio}")

    if video_type_radio == "分镜视频":
        video_type = "divison"
    else:
        video_type = "sequnce"
    # 清空 gallery_output
    return []


def generate_image(video_type_radio, user_prompt):
    logger.info(f"Selected video_type_radio: {video_type_radio}, Prompt: {user_prompt}")
    logger.info(f"Initial   user prompt : {user_prompt}")
    logger.info(f"prompt_enhanced_enabled : {prompt_enhanced_enabled}")

    if prompt_enhanced_enabled:
        user_prompt = _prompt_extension(user_prompt)
        logger.info(f"Extension user prompt : {user_prompt}")

    if video_type_radio == '连续视频':
        return generate_image_nova(user_prompt,video_type_radio)
    else:
        return create_divison_images(user_prompt,video_type_radio)

    
def extract_generated_video(task_id):
        video_path = f"./generated_videos/{task_id}_caption.mp4"
        if os.path.exists(video_path):
            return video_path
        else:
            gr.Info("未找到对应的视频文件")
            return None

def create_video(image_paths,gradio_video_type):
    global video_type    
    if not image_paths:
        gr.Info("图像为空，请先创建图像")
        return None
    print("视频类型:",gradio_video_type)
    if gradio_video_type == "连续视频":
        gr.Info("连续视频生成会依次生成，请耐心等待")
        return create_sequence_video(image_paths)
    else:
        return create_division_video(image_paths)

def create_video_with_task_id(image_paths,gradio_video_type,video_task_id):
    global video_type    
    if not image_paths:
        gr.Info("图像为空，请先创建图像")
        return None
    print("视频类型:",gradio_video_type)
    if gradio_video_type == "连续视频":
        gr.Info("连续视频生成会依次生成，请耐心等待")
        return create_sequence_video(image_paths,video_task_id)
    else:
        return create_division_video(image_paths,video_task_id)

    
def generate_task_id():
    task_id = str(random.randint(10000, 99999))
    return task_id
    
# Create the Gradio interface
with gr.Blocks() as demo:
    with gr.Column():
        gr.Markdown(
            """
            # GenAI Art Gallery
            """
        )
        
        # New Block for model selection, prompt, and warning
        with gr.Row():
            # Left column for inputs
            with gr.Column(scale=2):
                # Dropdown for model selection
                #model_dropdown = gr.Dropdown(
                #    choices=["Flux", "Nova Canvas"],
                #    # choices=["Nova Canvas"],
                #    label="选择模型",
                #    value="Nova Canvas",
                #    interactive=True
                #)

                # Text input for the prompt
                text_input = gr.Textbox(
                    label="输入提示词",
                    placeholder="群山后美丽的落日",
                    lines=3
                )

                prompt_enhanced_radio = gr.Radio(["是", "否"], label="启用提示词增强")
                video_type_radio = gr.Radio(["分镜视频", "连续视频"], label="生成视频类型",value="连续视频")
            
            # Right column for warning
            with gr.Column(scale=1):
                gr.Markdown(
                    """
                    ⚠️ Legal Disclaimer: 
                    
                    **Do not input sensitive data. Prompts
                      and generated images may be used 
                      during event util 12/10/2024
                      but will not be stored beyond the event.**
                    """,
                    elem_classes="warning-text"
                )
        
        with gr.Row():
            with gr.Column():
                # Generate button
                generate_btn = gr.Button("生成图片")

        # 下栏：模板选择和图像显示
        with gr.Row():
            # 模板下拉框
            template_dropdown = gr.Dropdown(
                choices=list(PROMPT_TEMPLATES.keys()),
                label="提示词模版"
            )
            
        with gr.Row():
            with gr.Column():
                # Output image display
                gallery_output = gr.Gallery(
                    label="生成的图片",
                    show_label=True,
                    elem_id="gallery",
                    columns=[1],
                    #rows=[2],
                    height="auto"
                )

        with gr.Row():
            with gr.Column():
                # 添加生成视频按钮
                generate_video_btn = gr.Button("生成视频")
        
        with gr.Row():
            with gr.Column(scale=2):
                # 添加视频任务 taskid 文本框
                video_task_id = gr.Textbox(label="视频任务 taskid", interactive=True)
            with gr.Column(scale=1):
                # 添加提取生成视频按钮
                extract_video_btn = gr.Button("提取生成视频")
            
        with gr.Row():
            with gr.Column():
                # 添加视频预览组件
                video_output = gr.Video(label="生成的视频")
        
        # Connect the inputs and output
        generate_btn.click(
            fn=generate_image,
            #fn=create_divison_images,
            inputs=[video_type_radio,text_input],
            outputs=gallery_output
        )

        # 当选择模版时更新 prompt 输入框
        template_dropdown.change(
            fn=update_prompt,
            inputs=template_dropdown,
            outputs=text_input
        )

        # 查看
        prompt_enhanced_radio.input(
            fn=enhance_prompt,
            inputs=prompt_enhanced_radio
        )
        
        video_type_radio.input(
            fn=video_type,
            inputs=video_type_radio,
            outputs=gallery_output
        )
        
        
        # 添加生成视频的事件连接
        #generate_video_btn.click(
        #        fn=create_video,
        #        inputs=[gallery_output,video_type_radio],
        #        outputs=[video_output,video_task_id],
        #        api_name="create_video"
        #    ).then(
        #        lambda: gr.Info("视频生成完成！")
        #    )
        
        generate_video_btn.click(
                fn=generate_task_id,
                outputs=video_task_id
            ).then(
                fn=create_video_with_task_id,
                inputs=[gallery_output, video_type_radio, video_task_id],
                outputs=video_output,
                api_name="create_video"
            )
        
        extract_video_btn.click(
            fn=extract_generated_video,
            inputs=[video_task_id],
            outputs=[video_output]
        )
        

# Launch the app
if __name__ == "__main__":
    demo.queue().launch(server_name="0.0.0.0", share=True)