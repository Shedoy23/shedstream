using System;
using System.Collections.Generic;

namespace BannerlordAutopilot
{
    // Pure camera geometry. No native agent/camera ownership and no per-frame allocations.
    internal sealed class BattleOverviewRig
    {
        internal struct Point
        {
            internal float X, Y, Z;
            internal bool Enemy;
            internal Point(float x, float y, float z, bool enemy) { X=x; Y=y; Z=z; Enemy=enemy; }
        }
        internal bool Ready { get; private set; }
        internal float Height { get; private set; } = 50f;
        internal float Pitch { get; private set; } = 30f;
        private int _challengerTicks;
        private float _challengerX, _challengerY;
        private float _yaw = 0.6f, _targetX, _targetY, _targetZ;
        internal float X, Y, Z;
        private float Distance => Height / (float)Math.Tan(Pitch * Math.PI / 180);
        internal float CameraX => X + (float)Math.Sin(_yaw) * Distance;
        internal float CameraY => Y - (float)Math.Cos(_yaw) * Distance;
        internal float CameraZ => Z + Height;
        internal void ResetPosition() { Ready=false; _challengerTicks=0; }
        internal void Zoom(float steps) { Height=Clamp(Height-steps*10f,20f,180f); }
        internal void Rotate(float dx,float dy)
        { _yaw += dx*0.006f; Pitch=Clamp(Pitch+dy*0.15f,25f,80f); }
        private static float Clamp(float x,float min,float max) => Math.Max(min,Math.Min(max,x));

        internal void Focus(IList<Point> points)
        {
            if (points.Count==0) return; // Keep the final battlefield framing during reinforcement gaps.
            int best=0, bestScore=-1;
            int step=Math.Max(1,(points.Count+31)/32);
            for(int i=0;i<points.Count;i+=step)
            {
                int friends=0,enemies=0;
                for(int j=0;j<points.Count;j++)
                    if(Near(points[i],points[j])) { if(points[j].Enemy) enemies++; else friends++; }
                int score=friends+enemies+3*Math.Min(friends,enemies);
                if(score>bestScore) { bestScore=score; best=i; }
            }
            var chosen=points[best];
            if(Ready)
            {
                var current=new Point(_targetX,_targetY,_targetZ,false);
                int friends=0,enemies=0;
                foreach(var point in points) if(Near(current,point))
                { if(point.Enemy) enemies++; else friends++; }
                int currentScore=friends+enemies+3*Math.Min(friends,enemies);
                if(currentScore>0 && !Near(current,chosen))
                {
                    // A remote reinforcement wave must remain substantially more
                    // important for ten seconds (20 half-second focus samples; 03.10:
                    // six seconds still read as the camera hopping between fights).
                    if(bestScore>currentScore*1.5f+5)
                    {
                        var challenger=new Point(_challengerX,_challengerY,0,false);
                        if(_challengerTicks==0 || !Near(challenger,chosen))
                        { _challengerX=chosen.X; _challengerY=chosen.Y; _challengerTicks=0; }
                        _challengerTicks++;
                    }
                    else _challengerTicks=0;
                    if(_challengerTicks<20) chosen=current;
                    else _challengerTicks=0;
                }
                else _challengerTicks=0;
            }
            float x=0,y=0,z=float.MinValue; int count=0;
            for(int i=0;i<points.Count;i++) if(Near(chosen,points[i]))
            { x+=points[i].X; y+=points[i].Y; z=Math.Max(z,points[i].Z); count++; }
            float nx=x/count, ny=y/count, dx=nx-_targetX, dy=ny-_targetY;
            // 03.10: a melee's centroid breathes a few metres every sample; following it
            // read as left-right sway. Re-aim only when the fight really moved (10 m).
            if(Ready && dx*dx+dy*dy<100f) return;
            _targetX=nx; _targetY=ny; _targetZ=z;
            if(!Ready) { X=_targetX; Y=_targetY; Z=_targetZ; Ready=true; }
        }
        private static bool Near(Point a,Point b)
        { float x=a.X-b.X,y=a.Y-b.Y; return x*x+y*y<=3600f; }
        internal void Step(float dt)
        {
            float alpha=1f-(float)Math.Exp(-Math.Max(0,Math.Min(dt,0.1f))*0.6f);
            X+=(_targetX-X)*alpha; Y+=(_targetY-Y)*alpha; Z+=(_targetZ-Z)*alpha;
        }
    }
}
