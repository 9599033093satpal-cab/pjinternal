from app import app, db, Job
with app.app_context():
    j = Job.query.get('167f1372-24e9-465c-a651-90143f20fab9')
    if j:
        print(f"Status: {j.status}")
        print(f"Progress: {j.progress}")
        print(f"Total Pages: {j.total_pages}")
        print(f"Current Page: {j.current_page}")
        print(f"Error: {j.error}")
        try:
            j.progress = j.progress # No change
            db.session.commit()
            print("DB Commit: SUCCESS")
        except Exception as e:
            print(f"DB Commit: FAILED - {str(e)}")
    else:
        print("Job not found")
