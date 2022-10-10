import csv
import json
import os
import re
from pathlib import Path
import httpx
from git import Repo

repo = Repo("/Users/glasnt/git/django/django")


DJANGO_TRAC = "https://code.djangoproject.com/jsonrpc"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

target_release = "4.1"
previous_release = "4.0"  # semver -1

start_commit = repo.commit(previous_release)  # 67d0c4644acfd7707be4a31e8976f865509b09ac
end_commit = repo.commit(target_release)  # c8eb9a7c451f7935a9eaafbb195acf2aa9fa867d
merge_base = repo.merge_base(start_commit, end_commit)[
    0
]  # c1689e65ffc64611bdc093baa5b767a18afea409

# shorter set for testing TODO fix.
#merge_base = repo.commit("d783ce3d8")
#end_commit = repo.commit("29fac6b6")


def print_to_csv(filename, data):
    print(filename, len(data))

    f = open(Path("data") / filename, "w")
    csv_w = csv.writer(f)
    csv_w.writerow(data[0].keys())
    for row in data:
        csv_w.writerow(row.values())

    f.close()


def get_git_tickets(target_release):

    commits = list(repo.iter_commits(str(merge_base) + ".." + str(end_commit)))

    git_commits = []
    git_trac_links = []
    tickets = []

    for commit in commits:
        git_commits.append(
            {
                "django_version": target_release,
                "commit_sha": commit.hexsha,
                "datetime": commit.authored_date,
                "author": commit.author.name,
                "author_email": commit.author.email,
                "committer": commit.committer.name,
                "committer_email": commit.committer.email,
                "message": commit.message,
            }
        )

        # Get all ticket references in message

        tickets = [x.replace("#", "") for x in re.findall("\#[0-9]*", commit.message)]

        for ticket in tickets:
            if ticket:
                git_trac_links.append(
                    {"commit_sha": commit.hexsha, "trac_ticket_id": ticket}
                )

    print_to_csv("git_commits.csv", git_commits)
    print_to_csv("git_trac_links.csv", git_trac_links)

    tickets = [k["trac_ticket_id"] for k in git_trac_links]
    return tickets


def get_trac_details(ticket_no):

    ticket_comments = []

    resp = httpx.post(
        DJANGO_TRAC,
        data=json.dumps(
            {"method": "ticket.get", "id": ticket_no, "params": [ticket_no]}
        ),
        headers={"Content-Type": "application/json"},
    )

    data = resp.json()["result"][3]

    ticket = {
        "ticket_id": ticket_no,
        "status": data["status"],
        "reporter": data["reporter"],
        "resolution": data["resolution"],
        "description": data["description"],
    }

    # struct ticket.changeLog(int id, int when=0)
    # Return the changelog as a list of tuples of the form
    # (time, author, field, oldvalue, newvalue, permanent).
    resp = httpx.post(
        DJANGO_TRAC,
        data=json.dumps(
            {"method": "ticket.changeLog", "id": ticket_no, "params": [ticket_no]}
        ),
        headers={"Content-Type": "application/json"},
    )

    changes = resp.json()["result"]

    for change in changes:
        ticket_comments.append(
            {
                "ticket_id": ticket_no,
                "datetime": change[0]["__jsonclass__"][1],
                "name": change[1],
                "change_type": change[2],
                "old_value": change[3],
                "new_value": change[4],
            }
        )

    return ticket, ticket_comments


def github_api(uri):

    resp = httpx.get(
        "https://api.github.com" + uri,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github.v3.raw",
        }
    )
    # Why no token being detected? :(

    if resp.status_code != 200:
        print(resp.headers)
        raise ValueError(resp.json()["message"])

    return resp.json()


def get_pull_requests(ticket_id):
    data = github_api(
        "/search/issues?q=repo:django/django+in:title+type:pr+"
        + "%23"
        + ticket_id
        + "%20"
        + "+%23"
        + ticket_id
        + "%2C"
        + "+%23"
        + ticket_id
        + "%3A"
        + "+%23"
        + ticket_id
        + "%29"
    )["items"]

    return [x["number"] for x in data]


def get_comments_from_pull_request(pull_request_id):
    comments = []

    # Comments
    data = github_api(f"/repos/django/django/pulls/{pull_request_id}/comments")

    for record in data:
        comments.append(
            {
                "user": record["user"]["login"],
                "commit_id": record["commit_id"],
                "message": record["body"],
                "pull_request": pull_request_id,
            }
        )

    # Review Comments
    data = github_api(f"/repos/django/django/issues/{pull_request_id}/comments")

    for record in data:
        comments.append(
            {
                "user": record["user"]["login"],
                "commit_id": None,
                "message": record["body"],
                "pull_request": pull_request_id,
            }
        )

    return comments


tickets_ids = get_git_tickets(target_release=target_release)

tickets = []
trac_ticket_comments = []

print("tickets", len(tickets_ids))

for ticket_no in tickets_ids:
    ticket, ticket_comments = get_trac_details(ticket_no)

    tickets.append(ticket)
    trac_ticket_comments += ticket_comments
print_to_csv("trac_tickets.csv", tickets)
print_to_csv("trac_ticket_comments.csv", trac_ticket_comments)

comments = []

for ticket_no in tickets_ids:
    pull_requests = get_pull_requests(ticket_no)

pull_requests = list(set(pull_requests))  # make unique.
print("Pull Requests:", len(pull_requests))

for request in pull_requests:
    comments += get_comments_from_pull_request(request)

print_to_csv("pull_request_comments.csv", comments)
