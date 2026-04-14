import json
from typing import Any
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import EnvSettingsSource, PydanticBaseSettingsSource
from pydantic.fields import FieldInfo


# Custom env source that treats agent_allowed_tools as a simple (non-JSON) field,
# allowing CSV values like "Bash,Read,Write" to pass through unparsed.
class _CsvAwareEnvSource(EnvSettingsSource):
    _CSV_FIELDS = {"agent_allowed_tools"}

    def prepare_field_value(
        self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool
    ) -> Any:
        if field_name in self._CSV_FIELDS:
            # Return as-is; the field_validator on the model will parse the CSV
            return value
        return super().prepare_field_value(field_name, field, value, value_is_complex)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    anthropic_api_key: str = Field(..., validation_alias="ANTHROPIC_API_KEY")
    agent_name: str = Field(..., validation_alias="AGENT_NAME")
    agent_description: str = Field(default="", validation_alias="AGENT_DESCRIPTION")
    agent_system_prompt: str = Field(default="", validation_alias="AGENT_SYSTEM_PROMPT")
    agent_model: str = Field(default="claude-sonnet-4-6", validation_alias="AGENT_MODEL")
    agent_max_turns: int = Field(default=10, validation_alias="AGENT_MAX_TURNS")
    agent_allowed_tools: list[str] = Field(
        default_factory=lambda: ["Read", "Bash"], validation_alias="AGENT_ALLOWED_TOOLS"
    )
    mcp_servers: dict[str, Any] = Field(default_factory=dict, validation_alias="MCP_SERVERS")
    bridge_port: int = Field(default=8080, validation_alias="BRIDGE_PORT")
    bridge_host: str = Field(default="0.0.0.0", validation_alias="BRIDGE_HOST")
    agent_url: str = Field(default="", validation_alias="AGENT_URL")
    memory_enabled: bool = Field(default=True, validation_alias="MEMORY_ENABLED")
    redis_url: str = Field(default="", validation_alias="REDIS_URL")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            _CsvAwareEnvSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )

    @field_validator("agent_allowed_tools", mode="before")
    @classmethod
    def _parse_tools(cls, v: Any) -> Any:
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @field_validator("mcp_servers", mode="before")
    @classmethod
    def _parse_mcp(cls, v: Any) -> Any:
        if isinstance(v, str):
            if not v.strip():
                return {}
            return json.loads(v)
        return v

    @field_validator("memory_enabled", mode="before")
    @classmethod
    def _parse_bool(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.lower() not in ("false", "0", "no")
        return v
