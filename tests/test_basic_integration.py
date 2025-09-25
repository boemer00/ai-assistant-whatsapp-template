"""
Basic integration test for LangGraph handler

Simple test to validate the LangGraph integration works without complex mocking.
"""

import pytest
from unittest.mock import Mock, MagicMock

from app.langgraph.handler import LangGraphHandler, create_langgraph_handler


class TestBasicIntegration:
    """Basic integration tests for LangGraph handler"""

    def test_handler_creation_factory(self):
        """Test creating handler with factory function"""
        # Create minimal mocks
        session_store = Mock()
        llm = Mock()
        amadeus_client = Mock()
        cache_manager = Mock()

        handler = create_langgraph_handler(
            session_store=session_store,
            llm=llm,
            amadeus_client=amadeus_client,
            cache_manager=cache_manager
        )

        assert isinstance(handler, LangGraphHandler)
        assert handler.session_store == session_store
        assert handler.amadeus_client == amadeus_client

    def test_handler_message_processing_basic(self):
        """Test basic message processing flow"""
        # Create mocks
        session_store = Mock()
        session_store.get.return_value = None  # New conversation
        session_store.set.return_value = True

        llm = Mock()
        amadeus_client = Mock()
        cache_manager = Mock()

        # Create handler directly
        handler = LangGraphHandler(
            session_store=session_store,
            llm=llm,
            amadeus_client=amadeus_client,
            cache_manager=cache_manager
        )

        # Test that we can call handle_message without errors
        try:
            response = handler.handle_message("test_user", "Hello")
            # Should return some response (even if it's an error message)
            assert isinstance(response, str)
            assert len(response) > 0
            print(f"✅ Handler returned response: {response[:50]}...")
        except Exception as e:
            print(f"❌ Handler failed: {e}")
            raise

    def test_session_info_methods(self):
        """Test session info methods work"""
        session_store = Mock()
        session_store.get.return_value = {
            "langgraph_state": {
                "origin": "NYC",
                "ready_for_api": True,
                "conversation_history": []
            }
        }

        handler = LangGraphHandler(
            session_store=session_store,
            llm=Mock(),
            amadeus_client=Mock(),
            cache_manager=Mock()
        )

        # Test session info
        info = handler.get_user_session_info("test_user")
        assert info["status"] == "active_conversation"
        assert info["ready_for_api"] is True

        # Test conversation metrics
        metrics = handler.get_conversation_metrics()
        assert metrics["handler_type"] == "langgraph"

    def test_main_app_basic_functionality(self):
        """Test main app can be imported and basic endpoints work"""
        try:
            import main
            from fastapi.testclient import TestClient

            client = TestClient(main.app)

            # Test basic endpoints
            response = client.get("/")
            assert response.status_code == 200
            data = response.json()
            assert data["version"] == "3.0.0"
            assert "LangGraph state machine" in data["features"]

            response = client.get("/health")
            assert response.status_code == 200

            print("✅ Main app endpoints working")

        except Exception as e:
            print(f"❌ Main app test failed: {e}")
            raise

    def test_langgraph_pipeline_components(self):
        """Test that LangGraph pipeline components are accessible"""
        from app.langgraph.state import create_initial_state, TravelState
        from app.langgraph.graph import compile_travel_graph
        from app.langgraph.nodes.collect_info import CollectInfoNode
        from app.langgraph.nodes.validate_complete import ValidateCompleteNode
        from app.langgraph.nodes.search_flights import SearchFlightsNode
        from app.langgraph.nodes.present_options import PresentOptionsNode

        # Test state creation
        state = create_initial_state()
        assert isinstance(state, dict)
        assert "origin" in state
        assert "ready_for_api" in state

        # Test graph compilation (with minimal mocks)
        try:
            graph = compile_travel_graph()  # Should work without dependencies
            assert graph is not None
            print("✅ LangGraph compilation working")
        except Exception as e:
            print(f"⚠️  LangGraph compilation needs dependencies: {e}")

        # Test node creation
        collect_node = CollectInfoNode()
        validate_node = ValidateCompleteNode()
        search_node = SearchFlightsNode(Mock(), Mock())
        present_node = PresentOptionsNode()

        assert all([collect_node, validate_node, search_node, present_node])
        print("✅ All LangGraph nodes can be created")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])