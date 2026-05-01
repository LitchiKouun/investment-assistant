import config
import backend.agent.investment_agent as ia

if __name__ == "__main__":
    print(config.get_settings().llm_api_key)
    print(config.get_settings().llm_api_url)
    print(config.get_settings().llm_model_id)


    # 测试完整流程
    result = ia.run_investment_analysis("帮我分析一下药明康德今天的走势")
    print(result)