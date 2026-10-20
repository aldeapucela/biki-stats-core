from pydantic import BaseModel


class CollectorRunData(BaseModel):
    capture_id: str
