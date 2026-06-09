from openai.types.chat import ChatCompletionMessageParam

from app.agents.schemas import CoderOutput
from app.core.llm_client import AsyncLLMClient


async def run_coder_agent(client: AsyncLLMClient, task_description: str) -> CoderOutput:
    messages: list[ChatCompletionMessageParam] = [
        {
            "role": "system",
            "content": (
                "You are a senior full-stack engineer. Return only a structured artifact that "
                "matches the required schema."
            ),
        },
        {"role": "user", "content": task_description},
    ]
    response = await client.client.beta.chat.completions.parse(
        model=client.model,
        messages=messages,
        response_format=CoderOutput,
    )
    parsed = response.choices[0].message.parsed
    if parsed is None:
        raise RuntimeError("Coder Agent failed to produce structured output")
    return parsed
