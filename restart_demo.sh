#!/bin/bash

# 查找使用 7861 端口的进程
PID=$(lsof -ti:7861)

# 如果找到进程，则杀掉它
if [ ! -z "$PID" ]; then
    echo "Killing process $PID using port 7861"
    kill -9 $PID
else
    echo "No process found using port 7861"
fi


# 清空 nohup.out 文件
> nohup.out

# 重新启动 ComfyUI
echo "Starting nova demo"
#nohup python3 ./webserver_video_full.py &
nohup python3 ./webserver_video_enhance.py &

echo "nova demo restarted"
