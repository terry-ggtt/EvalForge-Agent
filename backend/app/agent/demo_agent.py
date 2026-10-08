from app.agent.base import BaseAgent


class DemoAgent(BaseAgent):
    async def run(
        self,
        input_text: str,
    ) -> dict:
        return {
            "answer": f"Demo Agent response: {input_text}"
        }