"""Audio format the pipeline runs at, fixed by each transport."""

from pydantic import BaseModel, ConfigDict


class AudioFormat(BaseModel):
    """Sample rates of the pipeline's input and output audio."""

    model_config = ConfigDict(frozen=True)

    input_sample_rate_hz: int
    output_sample_rate_hz: int
