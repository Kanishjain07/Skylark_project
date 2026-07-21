import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import DataQuality from "./DataQuality.jsx";

// Wrap tables so wide ones scroll horizontally instead of breaking the layout.
const markdownComponents = {
  table: ({ node, ...props }) => (
    <div className="table-wrap">
      <table {...props} />
    </div>
  ),
};

export default function Message({ message }) {
  const isUser = message.role === "user";
  return (
    <div className={`msg ${isUser ? "user" : "assistant"}`}>
      <span className="role">{isUser ? "You" : "Agent"}</span>
      <div className="bubble">
        {isUser ? (
          <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{message.content}</p>
        ) : (
          <div className="markdown">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeRaw]}
              components={markdownComponents}
            >
              {message.content}
            </ReactMarkdown>
          </div>
        )}
      </div>
      {!isUser && <DataQuality dataQuality={message.dataQuality} />}
    </div>
  );
}
