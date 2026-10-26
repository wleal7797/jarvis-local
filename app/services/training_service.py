"""Módulo de entrenamiento, parte 1: calificar respuestas con 👍 / 👎.

Cada 👎 puede traer la respuesta correcta. Esa corrección se convierte en un ejemplo de
entrenamiento (pregunta del usuario → respuesta corregida) dentro del dataset
`correcciones-personales`, marcado como personal: nunca se enviará a Colab ni a Kaggle.
En la Etapa 12 esos ejemplos ajustan el modelo con LoRA.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Feedback, TrainingExample
from app.repositories import ConversationRepository
from app.repositories.training_repository import TrainingRepository

CORRECTIONS_DATASET = "correcciones-personales"
CORRECTIONS_DESCRIPTION = "Respuestas corregidas por el dueño desde el chat (👎 + corrección)."


class MessageNotRatableError(LookupError):
    """El mensaje no existe, no es del usuario o no es una respuesta de JARVIS."""


@dataclass(frozen=True)
class Rating:
    message_id: int
    rating: int
    correction: str | None
    training_example: bool


class TrainingService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def rate(
        self, user_id: int, message_id: int, rating: int, correction: str | None = None
    ) -> Rating:
        """Califica (o vuelve a calificar) una respuesta de JARVIS."""
        correction = (correction or "").strip() or None
        async with self._session_factory() as session:
            conversations = ConversationRepository(session)
            message = await conversations.message_for_user(message_id, user_id)
            if message is None or message.role != "assistant":
                raise MessageNotRatableError(message_id)

            repo = TrainingRepository(session)
            feedback = await repo.feedback_for_message(message_id)
            if feedback is None:
                feedback = await repo.add(
                    Feedback(message_id=message_id, user_id=user_id, rating=rating)
                )
            feedback.rating = rating
            feedback.correction = correction
            feedback.use_for_training = correction is not None

            examples: list[TrainingExample] = []
            if correction is not None:
                question = await self._question_for(conversations, message)
                if question:
                    dataset = await repo.dataset(
                        CORRECTIONS_DATASET, CORRECTIONS_DESCRIPTION, personal=True
                    )
                    examples.append(
                        TrainingExample(
                            dataset_id=dataset.id,
                            origin="feedback",
                            feedback_id=feedback.id,
                            user_prompt=question,
                            assistant_answer=correction,
                        )
                    )
            await repo.replace_examples(feedback.id, examples)
            await session.commit()
            return Rating(
                message_id=message_id,
                rating=rating,
                correction=correction,
                training_example=bool(examples),
            )

    @staticmethod
    async def _question_for(repo: ConversationRepository, reply) -> str | None:
        """El mensaje del usuario que originó esa respuesta."""
        messages = await repo.messages(reply.conversation_id)
        previous = None
        for message in messages:
            if message.id == reply.id:
                return previous.content if previous is not None else None
            if message.role == "user":
                previous = message
        return None
