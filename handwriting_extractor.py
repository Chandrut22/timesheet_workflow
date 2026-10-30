
import base64
import mimetypes
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

load_dotenv()

llm = ChatOpenAI(
    model="gemma4:31b-cloud",
    api_key=os.environ["OLLAMA_API_KEY"],
    base_url=os.getenv(
        "OLLAMA_BASE_URL",
        "https://ollama.com/v1",
    ),
    temperature=0,
    timeout=120,
    max_retries=2,
)


def extract_handwriting(image_path: str) -> str:
    path = Path(image_path)

    if not path.is_file():
        raise FileNotFoundError(f"Image not found: {path}")

    mime_type, _ = mimetypes.guess_type(path.name)

    if mime_type not in {
        "image/jpeg",
        "image/png",
        "image/webp",
    }:
        raise ValueError("Only JPG, PNG, and WebP are supported.")

    image_base64 = base64.b64encode(
        path.read_bytes()
    ).decode("utf-8")

    image_url = (
        f"data:{mime_type};base64,{image_base64}"
    )

    messages = [
        SystemMessage(
            content="""
You are a handwriting transcription specialist.

Transcribe the supplied image accurately.

Rules:
- Preserve the original spelling, dates, and numbers.
- Preserve decimal points in hour values.
- Never guess unreadable text; mark it as [UNCLEAR].
- Preserve table rows and columns.
- Do not calculate, correct, or infer missing values.
- Distinguish regular hours from overtime hours.
- Return only the transcription.
"""
        ),
        HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": (
                        "Transcribe all handwritten text in "
                        "this timesheet image."
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": image_url},
                },
            ]
        ),
    ]

    response = llm.invoke(messages)
    return str(response.content)


if __name__ == "__main__":
    result = extract_handwriting(
        r"C:\Users\User\Downloads\1000248105.jpg"
    )
    print(result)

    result = extract_handwriting(
        r"C:\Users\User\Downloads\1000248104.jpg"
    )
    print(result)
