"use client";

import { useState, useRef, useEffect } from "react";

interface DebugInfo {
  intent: string;
  retrieved_knowledge: any[];
  steps: { action: string; rationale: string; tool: string | null; tool_args: any }[];
}

interface LogEntry {
  userMessage: string;
  debug: DebugInfo;
}

export default function Chat() {
  const [activeTab, setActiveTab] = useState<"chat" | "logs">("chat");
  const [messages, setMessages] = useState<{ role: "user" | "agent"; text: string }[]>([
    { role: "agent", text: "Xin chào! Mình là Tư vấn viên Telesale. Mình có thể giúp gì cho bạn hôm nay?" }
  ]);
  const [debugLogs, setDebugLogs] = useState<LogEntry[]>([]);
  const [input, setInput] = useState("");
  const [customerPhone, setCustomerPhone] = useState("0984726714");
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Generate a random session ID on client mount to prevent SSR hydration mismatch
  const [sessionId, setSessionId] = useState("");

  useEffect(() => {
    setSessionId(Math.random().toString(36).substring(7));
  }, []);

  useEffect(() => {
    if (activeTab === "chat") {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, activeTab]);

  const sendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", text: userMessage }]);
    setIsLoading(true);

    try {
      const apiUrl = process.env.NODE_ENV === "development" 
        ? "http://localhost:8000/api/chat" 
        : "https://sudo-code-2026-group-9.onrender.com/api/chat"; 

      const response = await fetch(apiUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_id: sessionId,
          message: userMessage,
          customer_phone: customerPhone || null,
        }),
      });

      const data = await response.json();
      setMessages((prev) => [...prev, { role: "agent", text: data.response || "Sorry, I couldn't process that." }]);
      
      if (data.debug) {
        setDebugLogs((prev) => [...prev, { userMessage, debug: data.debug }]);
      }
    } catch (error) {
      console.error(error);
      setMessages((prev) => [...prev, { role: "agent", text: "Connection error. Please try again." }]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex h-screen bg-[#F4F1EA] text-gray-900 font-sans overflow-hidden">
      {/* Sidebar */}
      <aside className="w-64 bg-[#111111] text-[#F4F1EA] flex-col hidden md:flex shrink-0">
        <div className="p-6">
          <h1 className="text-2xl font-bold tracking-tight text-white">Telesale Hub</h1>
        </div>
        <nav className="flex-1 px-4 space-y-2 mt-4">
          <button 
            onClick={() => setActiveTab("chat")}
            className={`flex items-center w-full gap-3 px-4 py-3 rounded-xl transition-colors font-medium border ${
              activeTab === "chat" ? "bg-white/10 border-white/5 text-white" : "border-transparent text-white/50 hover:bg-white/5"
            }`}
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
            Chat Agent
          </button>
          
          <button 
            onClick={() => setActiveTab("logs")}
            className={`flex items-center w-full gap-3 px-4 py-3 rounded-xl transition-colors font-medium border ${
              activeTab === "logs" ? "bg-white/10 border-white/5 text-white" : "border-transparent text-white/50 hover:bg-white/5"
            }`}
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg>
            Debug Logs
          </button>

          <button className="flex items-center w-full gap-3 px-4 py-3 rounded-xl transition-colors text-white/30 font-medium cursor-not-allowed">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 3v18h18"></path><path d="M18.7 8l-5.1 5.2-2.8-2.7L7 14.3"></path></svg>
            Analytics (Soon)
          </button>
        </nav>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col h-screen relative min-w-0">
        {/* Header */}
        <header className="bg-[#F4F1EA]/80 backdrop-blur-md border-b border-black/10 py-4 px-6 flex items-center justify-between z-10 shrink-0">
          <h2 className="text-xl font-bold text-black md:hidden">Telesale Hub</h2>
          
          <div className="md:hidden flex gap-2">
            <button 
              onClick={() => setActiveTab("chat")}
              className={`px-3 py-1 text-xs font-semibold rounded-full border ${activeTab === "chat" ? "bg-black text-white" : "border-black/20"}`}
            >Chat</button>
            <button 
              onClick={() => setActiveTab("logs")}
              className={`px-3 py-1 text-xs font-semibold rounded-full border ${activeTab === "logs" ? "bg-black text-white" : "border-black/20"}`}
            >Logs</button>
          </div>

          <div className="flex gap-3 ml-auto items-center">
            <input
              type="text"
              placeholder="SĐT (VD: 0984726714)"
              value={customerPhone}
              onChange={(e) => setCustomerPhone(e.target.value)}
              className="text-xs text-black/80 bg-white border border-black/10 px-3 py-1.5 rounded-full outline-none focus:border-black/30 placeholder-black/30 w-36"
              title="Nhập SĐT khách hàng (VD: 0984726714)"
            />
            <div className="text-xs text-black/60 bg-black/5 px-3 py-1.5 rounded-full font-semibold tracking-wide hidden sm:block">
              Session: {sessionId}
            </div>
          </div>
        </header>

        {activeTab === "chat" ? (
          <>
            {/* Chat Scroll Area */}
            <div className="flex-1 overflow-y-auto p-4 sm:p-6 scroll-smooth">
              <div className="max-w-3xl mx-auto space-y-6 pb-4">
                {messages.map((msg, idx) => (
                  <div key={idx} className={`flex items-start gap-3 ${msg.role === "user" ? "flex-row-reverse" : "flex-row"}`}>
                    {/* Avatar */}
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-1 ${
                      msg.role === "user" ? "bg-[#111111] text-white" : "bg-white border border-black/10 text-black"
                    }`}>
                      {msg.role === "user" ? (
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
                      ) : (
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 8V4H8"></path><rect width="16" height="12" x="4" y="8" rx="2"></rect><path d="M2 14h2"></path><path d="M20 14h2"></path><path d="M15 13v2"></path><path d="M9 13v2"></path></svg>
                      )}
                    </div>

                    {/* Message Bubble */}
                    <div
                      className={`max-w-[85%] sm:max-w-[75%] rounded-2xl px-5 py-3.5 shadow-sm leading-relaxed ${
                        msg.role === "user"
                          ? "bg-[#111111] text-[#F4F1EA] rounded-tr-sm"
                          : "bg-white border border-black/5 text-gray-800 rounded-tl-sm"
                      }`}
                    >
                      {msg.text}
                    </div>
                  </div>
                ))}
                
                {isLoading && (
                  <div className="flex items-start gap-3 flex-row">
                    {/* Agent Avatar for Loading */}
                    <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-1 bg-white border border-black/10 text-black">
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 8V4H8"></path><rect width="16" height="12" x="4" y="8" rx="2"></rect><path d="M2 14h2"></path><path d="M20 14h2"></path><path d="M15 13v2"></path><path d="M9 13v2"></path></svg>
                    </div>
                    <div className="bg-white border border-black/5 text-gray-500 rounded-2xl rounded-tl-sm px-5 py-4 shadow-sm flex items-center space-x-2">
                      <div className="w-2 h-2 bg-black/40 rounded-full animate-bounce"></div>
                      <div className="w-2 h-2 bg-black/40 rounded-full animate-bounce" style={{ animationDelay: "0.15s" }}></div>
                      <div className="w-2 h-2 bg-black/40 rounded-full animate-bounce" style={{ animationDelay: "0.3s" }}></div>
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>
            </div>

            {/* Input Area */}
            <div className="bg-[#F4F1EA] p-4 sm:p-6 border-t border-black/10 shrink-0">
              <div className="max-w-3xl mx-auto">
                <form onSubmit={sendMessage} className="flex gap-3">
                  <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder="Nhắn tin cho tư vấn viên..."
                    className="flex-1 border border-black/15 bg-white text-black rounded-full px-6 py-3.5 focus:outline-none focus:ring-2 focus:ring-black/20 focus:border-black shadow-sm transition-all"
                    disabled={isLoading}
                  />
                  <button
                    type="submit"
                    disabled={isLoading || !input.trim()}
                    className="bg-[#111111] text-[#F4F1EA] px-8 py-3.5 rounded-full font-medium hover:bg-black disabled:opacity-50 transition-all shadow-sm flex items-center gap-2"
                  >
                    Gửi
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
                  </button>
                </form>
              </div>
            </div>
          </>
        ) : (
          /* Debug Logs Area */
          <div className="flex-1 overflow-y-auto p-4 sm:p-8 bg-white">
            <div className="max-w-4xl mx-auto space-y-8 pb-12">
              <div className="border-b border-gray-200 pb-4">
                <h2 className="text-2xl font-bold text-gray-900">Agent Execution Logs</h2>
                <p className="text-gray-500 mt-1">Trang này hiển thị suy nghĩ nội bộ và trạng thái LangGraph của Bot.</p>
              </div>
              
              {debugLogs.length === 0 ? (
                <div className="text-center py-20 text-gray-400 border-2 border-dashed rounded-2xl border-gray-200">
                  <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="mx-auto mb-4 opacity-50"><rect width="18" height="18" x="3" y="4" rx="2" ry="2"></rect><line x1="16" x2="16" y1="2" y2="6"></line><line x1="8" x2="8" y1="2" y2="6"></line><line x1="3" x2="21" y1="10" y2="10"></line><path d="m9 16 2 2 4-4"></path></svg>
                  <p>Chưa có log nào. Hãy qua Tab Chat và bắt đầu trò chuyện để ghi log!</p>
                </div>
              ) : (
                <div className="space-y-8">
                  {debugLogs.map((log, i) => (
                    <div key={i} className="border border-gray-200 rounded-2xl p-5 sm:p-6 shadow-sm bg-[#F4F1EA]/30">
                      <div className="flex items-center gap-3 mb-6">
                        <div className="bg-black text-white px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wide">Lượt {i + 1}</div>
                        <div className="font-semibold text-lg text-gray-900">"{log.userMessage}"</div>
                      </div>
                      
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                        {/* Intent Panel */}
                        <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm">
                          <div className="flex items-center gap-2 mb-2 text-gray-500">
                            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2a10 10 0 1 0 10 10 4 4 0 0 1-5-5 4 4 0 0 1-5-5"></path><path d="M8.5 8.5v.01"></path><path d="M16 15.5v.01"></path><path d="M12 12v.01"></path><path d="M11 17v.01"></path><path d="M7 14v.01"></path></svg>
                            <span className="text-xs uppercase font-bold tracking-wider">Phân tích Intent</span>
                          </div>
                          <div className="font-mono text-blue-700 bg-blue-50 px-3 py-1.5 rounded-lg inline-block text-sm border border-blue-100">
                            {log.debug.intent}
                          </div>
                        </div>
                        
                        {/* RAG Panel */}
                        <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm">
                          <div className="flex items-center justify-between mb-2 text-gray-500">
                            <div className="flex items-center gap-2">
                              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" x2="12" y1="3" y2="15"></line></svg>
                              <span className="text-xs uppercase font-bold tracking-wider">Lấy dữ liệu RAG</span>
                            </div>
                            <span className="text-xs font-semibold bg-gray-100 px-2 py-0.5 rounded-full text-gray-600">
                              {log.debug.retrieved_knowledge.length} items
                            </span>
                          </div>
                          {log.debug.retrieved_knowledge.length > 0 ? (
                            <pre className="text-xs p-3 bg-gray-50 rounded-lg overflow-x-auto border border-gray-100 text-gray-600 max-h-32">
                              {JSON.stringify(log.debug.retrieved_knowledge, null, 2)}
                            </pre>
                          ) : (
                            <div className="text-sm text-gray-400 italic">Không tìm thấy kiến thức liên quan.</div>
                          )}
                        </div>
                      </div>
                      
                      {/* Planner Steps */}
                      <div>
                        <div className="flex items-center gap-2 mb-3 text-gray-500 ml-1">
                          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"></circle><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"></path><path d="M2 12h20"></path></svg>
                          <span className="text-xs uppercase font-bold tracking-wider">Suy nghĩ của LLM (Planner)</span>
                        </div>
                        <div className="space-y-3">
                          {log.debug.steps.map((step, j) => (
                            <div key={j} className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm relative overflow-hidden">
                              <div className="absolute top-0 left-0 w-1 h-full bg-black"></div>
                              <div className="flex justify-between items-start mb-3 pl-2">
                                <span className="font-mono text-purple-700 bg-purple-50 px-2 py-1.5 rounded-lg text-sm font-semibold border border-purple-100">
                                  action: {step.action}
                                </span>
                                {step.tool && (
                                  <span className="font-mono text-xs text-orange-700 bg-orange-50 px-2 py-1 rounded-md border border-orange-100">
                                    Tool: {step.tool}
                                  </span>
                                )}
                              </div>
                              <div className="text-sm text-gray-700 leading-relaxed pl-2">
                                <span className="font-semibold text-gray-900 mr-2">Rationale:</span>
                                {step.rationale}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
