from abc import ABC, abstractmethod

class BaseAgent(ABC):
    @abstractmethod
    async def run(
        self,
        input_text:str
    )->dict:
        pass
