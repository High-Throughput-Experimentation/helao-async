from pydantic import BaseModel

class S3Locator(BaseModel):
    bucket: str
    key: str
    region: str
    
    @property
    def url(self):
        return f"s3://{self.bucket}/{self.key}"