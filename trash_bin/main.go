package main

import (
	"errors"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"encoding/json"
	"regexp"
	"log"
	bolt "go.etcd.io/bbolt"
)

func getRoot(w http.ResponseWriter, r *http.Request) {
	log.Println("got / request")
	io.WriteString(w, "koha proxy server running")
}

	
func dbHandler(){
	db, err := bolt.Open("my.db", 0600, nil)
	if err != nil {
		log.Fatal(err)
	}
	defer db.Close()
}

func loginHandler(w http.ResponseWriter, r *http.Request, db *bolt.DB) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var username, password string

	if r.Header.Get("Content-Type") == "application/json" {
		type Login struct {
			Username string `json:"username"`
			Password string `json:"password"`
		}
		var creds Login
		if err := json.NewDecoder(r.Body).Decode(&creds); err != nil {
			http.Error(w, "invalid json", http.StatusBadRequest)
			return
		}
		username, password = creds.Username, creds.Password
	} else {
		if err := r.ParseForm(); err != nil {
			http.Error(w, "error parsing form", http.StatusBadRequest)
			return
		}
		username = r.FormValue("username")
		password = r.FormValue("password")
	}

	if username == "" || password == "" {
		http.Error(w, "username and password are required", http.StatusBadRequest)
		return
	}

	form := url.Values{}
	form.Set("has-search-query", "")
	form.Set("koha_login_context", "opac")
	form.Set("userid", username)
	form.Set("password", password)

	loginReq, err := http.NewRequest("POST", "http://opac.nitc.ac.in/cgi-bin/koha/opac-user.pl", strings.NewReader(form.Encode()))
	if err != nil {
		http.Error(w, "failed creating login request", http.StatusInternalServerError)
		return
	}
	loginReq.Header.Set("Content-Type", "application/x-www-form-urlencoded")

	client := &http.Client{
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}

	loginResp, err := client.Do(loginReq)
	if err != nil {
		http.Error(w, "failed sending login request", http.StatusBadGateway)
		return
	}
	defer loginResp.Body.Close()

	if loginResp.StatusCode == 200 {
		http.Error(w, "login failed", http.StatusUnauthorized)
		return
	}
	
	var sessionID string
	for _, cookie := range loginResp.Cookies() {
		if cookie.Name == "CGISESSID" {
			sessionID = cookie.Value
			break
		}
	}
	log.Println("got session id", sessionID)


	infoReq, err := http.NewRequest("GET", "http://opac.nitc.ac.in/cgi-bin/koha/opac-user.pl?has-search-query=", nil)
	if err != nil {
		http.Error(w, "failed creating request", http.StatusInternalServerError)
		return
	}
	infoReq.AddCookie(&http.Cookie{
		Name:  "CGISESSID",
		Value: sessionID,
	})

	infoResp, err := client.Do(infoReq)
	if err != nil {
		http.Error(w, "failed sending request", http.StatusBadGateway)
		return
	}
	defer infoResp.Body.Close()

	bodyBytes, err := io.ReadAll(infoResp.Body)
	if err != nil {
    		http.Error(w, "failed processing koha response", http.StatusInternalServerError)
    		return
	}

	re := regexp.MustCompile(`(?i)<p>Hello,\s*([A-Z\s]+?)<br\s*/?>`)
        match := re.FindSubmatch(bodyBytes)
        if len(match) >= 2 {
                name := string(match[1])
		io.WriteString(w, "Welcome, " + strings.TrimSpace(name) + "\n")
        } else {
		http.Error(w, "failed fetching user name", http.StatusInternalServerError)
        }
}



func main() {
	db, err := bolt.Open("my.db", 0600, nil)
        if err != nil {
                log.Fatal(err)
        }
        defer db.Close()

	err = db.Update(func(tx *bolt.Tx) error {
		_, err := tx.CreateBucketIfNotExists([]byte("sessions"))
		return err
	})
	if err != nil {
		log.Fatal(err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/", getRoot)
	mux.HandleFunc("/login", func(w http.ResponseWriter, r *http.Request) {
    		loginHandler(w, r, db)
	})

	server := &http.Server{
		Addr:    ":4040",
		Handler: mux,
	}

	log.Println("server listening on 4040")
	err := server.ListenAndServe()
	if errors.Is(err, http.ErrServerClosed) {
		log.Println("server closed")
	} else if err != nil {
		log.Printf("error starting server: %s\n", err)
		os.Exit(1)
	}
}

