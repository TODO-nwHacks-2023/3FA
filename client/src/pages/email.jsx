import * as React from "react";
import { handleSubmit } from "../hooks/handleSubmit";
import { useLocation, useNavigate } from "react-router-dom";
import { Backdoor } from "./backdoor.jsx";
import { sessionContext } from "../app.jsx";
import { DisplayText } from "../components/DisplayText.jsx";

export function Email() {
  const navigate = useNavigate();
  const [email, setEmail] = React.useState("");
  const [session, setSession] = React.useContext(sessionContext);
  const [text, setText] = React.useState("");
  const submitButton = document.getElementById("submitButton");

  React.useEffect(() => {
    setText(""); // clear text on submit
  }, [submitButton]);

  return (
    <>
      <h1>Enter your Email</h1>
      <DisplayText text={text} />
      <form
        onSubmit={(event) => {
          handleSubmit(event, {
            endpoint: "email",
            data: email,
            navigate: navigate,
            session: session,
            setSession: setSession,
            setText: setText,
          });
        }}
      >
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input id="submitButton" type="submit" value="Submit" />
      </form>
      <Backdoor />
    </>
  );
}
