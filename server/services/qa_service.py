from server.agents.question_agent import QuestionAgent
from server.rag.embedder import Embedder
from server.rag.retriever import Retriever
from server.rag.prompt_builder import build_prompt
from server.storage.embedding_repo import EmbeddingRepo
from server.models.decision import DecisionResult
from server.config.settings import SETTINGS


class QAService:
    def __init__(self):
        self.agent = QuestionAgent()
        self.embedder = Embedder(dim=SETTINGS.EMBED_DIM)
        self.emb_repo = EmbeddingRepo()
        self.retriever = Retriever(self.emb_repo)

    def handle_question(self, question: str, doc_id: str = None):
        decision: DecisionResult = self.agent.analyze(question)
        qvec = self.embedder.embed_text(question)
        top = self.retriever.retrieve(qvec, top_k=decision.top_k, doc_id=doc_id)
        prompt = build_prompt(question, decision.__dict__, top)
        return {"prompt": prompt, "decision": decision.__dict__, "top_chunks": top}
