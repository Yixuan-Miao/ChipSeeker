from chipseeker.utils import load_json, save_json


DEFAULT_CONFIG = {
    "llm_api_key": "",
    "llm_base_url": "https://api.deepseek.com",
    "llm_model": "deepseek-chat",
    "provider_preset": "DeepSeek",
    "embedding_model": "all-MiniLM-L6-v2",
    "emb_api_key": "",
    "cloud_access_base_url": "https://chipseeker.online",
    "cloud_access_email": "",
    "cloud_access_code": "",
    "cloud_access_enabled": False,
    "onboarding_completed": False,
}

LEGACY_RATING_MAP = {
    "Unrated": "Unrated",
    "Masterpiece": "Masterpiece",
    "Solid": "Solid",
    "Average": "Average",
    "Marginal": "Marginal",
    "Poor": "Poor",
}


def load_app_config(config_paths):
    for path in config_paths:
        loaded = load_json(path, None)
        if isinstance(loaded, dict):
            merged = DEFAULT_CONFIG.copy()
            merged.update(loaded)
            return merged
    return DEFAULT_CONFIG.copy()


class UserDataStore:
    def __init__(self, filepath):
        self.filepath = filepath
        self.data = load_json(filepath, {})

    def get(self, title):
        item = self.data.get(
            title,
            {"rating": "Unrated", "open_count": 0, "comments": "", "matched_queries": []},
        )
        item["rating"] = LEGACY_RATING_MAP.get(item["rating"], item["rating"])
        return item

    def update(self, title, key, value):
        if title not in self.data:
            self.data[title] = {
                "rating": "Unrated",
                "open_count": 0,
                "comments": "",
                "matched_queries": [],
            }
        self.data[title][key] = value
        save_json(self.filepath, self.data)
