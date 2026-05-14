import json
from pathlib import Path
from typing import Any


class MissingOpenAIAPIKey(RuntimeError):
    pass


def make_response_request(
    *,
    custom_id: str,
    model: str,
    prompt: str,
    report_id: str | None = None,
    prompt_version: str | None = None,
) -> dict[str, Any]:
    return {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/responses",
        "body": {
            "model": model,
            "input": prompt,
            "temperature": 0,
            "metadata": {
                "report_id": report_id,
                "prompt_version": prompt_version,
            },
        },
    }


def create_jsonl_file(requests: list[dict[str, Any]], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    with path.open("w", encoding="utf-8") as handle:
        for request in requests:
            custom_id = request.get("custom_id")
            if not custom_id:
                raise ValueError("batch request missing custom_id")
            if custom_id in seen:
                raise ValueError(f"duplicate custom_id: {custom_id}")
            seen.add(custom_id)
            handle.write(json.dumps(request, ensure_ascii=True) + "\n")
    return path


class OpenAIBatchClient:
    def __init__(self, api_key: str | None):
        if not api_key:
            raise MissingOpenAIAPIKey("OPENAI_API_KEY is required to submit or retrieve OpenAI batches.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("The openai Python SDK is not installed. Install project dependencies before submitting batches.") from exc
        self.client = OpenAI(api_key=api_key)

    def upload_batch_file(self, path: str | Path) -> Any:
        with Path(path).open("rb") as handle:
            return self.client.files.create(file=handle, purpose="batch")

    def create_batch(
        self,
        input_file_id: str,
        *,
        endpoint: str = "/v1/responses",
        completion_window: str = "24h",
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        return self.client.batches.create(
            input_file_id=input_file_id,
            endpoint=endpoint,
            completion_window=completion_window,
            metadata=metadata or {},
        )

    def retrieve_batch(self, openai_batch_id: str) -> Any:
        return self.client.batches.retrieve(openai_batch_id)

    def download_output_file(self, file_id: str, output_path: str | Path) -> Path:
        return self._download_file(file_id, output_path)

    def download_error_file(self, file_id: str, output_path: str | Path) -> Path:
        return self._download_file(file_id, output_path)

    def cancel_batch(self, openai_batch_id: str) -> Any:
        return self.client.batches.cancel(openai_batch_id)

    def _download_file(self, file_id: str, output_path: str | Path) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = self.client.files.content(file_id)
        if hasattr(content, "write_to_file"):
            content.write_to_file(str(path))
        else:
            data = content.read() if hasattr(content, "read") else bytes(content)
            path.write_bytes(data)
        return path
