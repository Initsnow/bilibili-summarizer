def read_prompt(filename: str) -> str:
    try:
        with open(f"prompt/{filename}.md", "r", encoding="utf-8") as file:
            content = file.read()
        return content
    except FileNotFoundError:
        raise FileNotFoundError(f"未找到prompt/{filename}.md文件")
    except Exception as e:
        raise Exception(f"读取文件时发生错误: {str(e)}")