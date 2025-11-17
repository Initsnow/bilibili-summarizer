from typing import Optional
import litellm
from litellm.files.main import ModelResponse
from litellm import Choices, Message
import os
os.getenv("GEMINI_API_KEY")


async def summarize(content: str, prompt: str) -> Optional[str]:
    response = await litellm.acompletion(
        # model="gemini/gemini-2.5-pro",
        model="gemini/gemini-2.5-flash",
        messages=[
            {"role": "developer", "content": prompt},
            {
                "role": "user",
                "content": f"以最简、高效、科学的方式总结以下内容：{content}",
            },
        ],
        reasoning_effort="high",
        temperature=0.6,
    )
    if isinstance(response, ModelResponse):
        if isinstance(response.choices, list) and response.choices:
            first_choice = response.choices[0]
            if (
                isinstance(first_choice, Choices)
                and isinstance(first_choice.message, Message)
                and isinstance(first_choice.message.content, str)
            ):
                result_str = first_choice.message.content
                return result_str
