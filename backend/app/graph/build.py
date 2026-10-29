from langgraph.graph import END, START, StateGraph

from app.graph.nodes.bisect import bisect_polluter
from app.graph.nodes.classify import classify
from app.graph.nodes.diagnose import diagnose
from app.graph.nodes.escalate import escalate
from app.graph.nodes.patch import patch
from app.graph.nodes.research import research
from app.graph.nodes.score import route, score_confidence
from app.graph.nodes.verify import verify
from app.graph.state import FlakeState


def build_flake_graph(checkpointer):
    """classify → bisect → research → diagnose → patch → verify → score → route → escalate."""
    graph = StateGraph(FlakeState)
    graph.add_node("classify", classify)
    graph.add_node("bisect", bisect_polluter)
    graph.add_node("research", research)
    graph.add_node("diagnose", diagnose)
    graph.add_node("patch", patch)
    graph.add_node("verify", verify)
    graph.add_node("score", score_confidence)
    graph.add_node("route", route)
    graph.add_node("escalate", escalate)
    graph.add_edge(START, "classify")
    graph.add_edge("classify", "bisect")
    graph.add_edge("bisect", "research")
    graph.add_edge("research", "diagnose")
    graph.add_edge("diagnose", "patch")
    graph.add_edge("patch", "verify")
    graph.add_edge("verify", "score")
    graph.add_edge("score", "route")
    graph.add_edge("route", "escalate")
    graph.add_edge("escalate", END)
    return graph.compile(checkpointer=checkpointer)
